#!/usr/bin/env python3
"""nox - LXC Container Manager"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time

NOX_DIR = os.path.expanduser("~/.nox")
CONTAINERS_DIR = os.path.join(NOX_DIR, "containers")
CONFIG_FILE = os.path.join(NOX_DIR, "config.json")
LXC_PATH = "/var/lib/lxc"

DEFAULT_CONFIG = {
    "defaults": {"os": "debian", "cpus": 1, "ram": 512, "disk": 5},
    "env": {},
}

# LXC template mappings
LXC_TEMPLATES = {
    "debian": "debian",
    "alpine": "alpine",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_dirs():
    os.makedirs(CONTAINERS_DIR, exist_ok=True)


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    ensure_dirs()
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def host_arch():
    m = os.uname().machine
    if m in ("aarch64", "arm64"):
        return "arm64"
    return "amd64"


def host_cpus():
    return os.cpu_count() or 1


def host_ram_mb():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    return 1024


def host_disk_gb(path="/"):
    st = os.statvfs(path)
    return (st.f_frsize * st.f_blocks) // (1024 ** 3)


def resolve_resource(value, host_total):
    """If value <= 1.0, treat as fraction of host_total. Otherwise absolute."""
    v = float(value)
    if v <= 1.0:
        return max(1, int(math.ceil(v * host_total)))
    return int(v)


def run(cmd, check=True, capture=True):
    """Run a shell command."""
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=capture, text=True)
    if check and r.returncode != 0:
        err = r.stderr.strip() if r.stderr else ""
        raise RuntimeError(f"Command failed: {cmd}\n{err}")
    return r


def lxc(args, check=True):
    """Run lxc command."""
    return run(f"sudo {args}", check=check)


def container_exists(name):
    r = lxc(f"lxc-info -n {name}", check=False)
    return r.returncode == 0


def container_state(name):
    r = lxc(f"lxc-info -n {name} -s", check=False)
    if r.returncode != 0:
        return None
    # Output format: "State:          RUNNING"
    for line in r.stdout.splitlines():
        if line.strip().startswith("State:"):
            return line.split(":", 1)[1].strip().upper()
    return None


def container_dir(name):
    return os.path.join(CONTAINERS_DIR, name)


def meta_path(name):
    return os.path.join(container_dir(name), "meta.json")


def load_meta(name):
    p = meta_path(name)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None


def save_meta(name, meta):
    d = container_dir(name)
    os.makedirs(d, exist_ok=True)
    with open(meta_path(name), "w") as f:
        json.dump(meta, f, indent=2)


def container_ip(name, timeout=60):
    """Get container IP address, waiting up to timeout seconds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = lxc(f"lxc-info -n {name} -iH", check=False)
        if r.returncode == 0:
            # lxc-info returns multiple IPs (IPv4 and IPv6), get first IPv4
            for line in r.stdout.strip().splitlines():
                ip = line.strip()
                if ip and ip != "-" and ":" not in ip:  # IPv4 only
                    return ip
        time.sleep(2)
    return None


def lxc_config_path(name):
    """Get path to LXC container config file."""
    return os.path.join(LXC_PATH, name, "config")


def set_resource_limits(name, vcpus, ram_mb):
    """Set cgroup resource limits for container."""
    config_path = lxc_config_path(name)

    # Build resource limit lines
    limits = []
    # CPU shares (cgroup v1) - 1024 shares per CPU
    limits.append(f"lxc.cgroup.cpu.shares = {vcpus * 1024}")
    # CPU max (cgroup v2) - quota/period format
    limits.append(f"lxc.cgroup2.cpu.max = {vcpus * 100000} 100000")

    # Memory limit
    ram_bytes = ram_mb * 1024 * 1024
    limits.append(f"lxc.cgroup.memory.limit_in_bytes = {ram_bytes}")
    limits.append(f"lxc.cgroup2.memory.max = {ram_bytes}")

    # Use sudo to read, modify, and write config
    for limit in limits:
        run(f"sudo sh -c 'echo \"{limit}\" >> {config_path}'")


# ---------------------------------------------------------------------------
# Setup script generation
# ---------------------------------------------------------------------------

def generate_setup_script(name, os_name, init_scripts=None, password=None):
    """Generate setup script that runs inside container."""
    cfg = load_config()
    env_vars = cfg.get("env", {})

    # Find SSH public key
    ssh_key = ""
    for keyfile in ["id_ed25519.pub", "id_rsa.pub"]:
        p = os.path.expanduser(f"~/.ssh/{keyfile}")
        if os.path.exists(p):
            with open(p) as f:
                ssh_key = f.read().strip()
            break

    shell = "/bin/bash" if os_name == "debian" else "/bin/ash"

    lines = ["#!/bin/sh", "set -e", ""]

    # Install openssh-server
    if os_name == "debian":
        lines.append("apt-get update")
        lines.append("DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server sudo")
        lines.append("mkdir -p /run/sshd")
    else:  # alpine
        lines.append("apk add --no-cache openssh-server sudo bash")
        lines.append("ssh-keygen -A")

    # Create nox user
    lines.append(f"adduser -D -s {shell} nox 2>/dev/null || useradd -m -s {shell} nox")
    lines.append("echo 'nox ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/nox")
    lines.append("chmod 440 /etc/sudoers.d/nox")

    # Set password
    if password:
        lines.append(f"echo 'nox:{password}' | chpasswd")

    # Add SSH key
    if ssh_key:
        lines.append("mkdir -p /home/nox/.ssh")
        lines.append(f"echo '{ssh_key}' > /home/nox/.ssh/authorized_keys")
        lines.append("chown -R nox:nox /home/nox/.ssh")
        lines.append("chmod 700 /home/nox/.ssh")
        lines.append("chmod 600 /home/nox/.ssh/authorized_keys")

    # Enable password auth
    lines.append("sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config")
    lines.append("sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config")

    # Set environment variables
    if env_vars:
        for k, v in env_vars.items():
            lines.append(f"echo '{k}={v}' >> /etc/environment")

    # Run init scripts
    if init_scripts:
        for idx, script_path in enumerate(init_scripts):
            if os.path.exists(script_path):
                lines.append(f"# Running init script {idx}")
                with open(script_path) as f:
                    script_content = f.read()
                script_lines = script_content.splitlines()
                for line in script_lines:
                    if line.startswith("#!"):
                        continue
                    if "set -euo pipefail" in line or "set -eo pipefail" in line:
                        lines.append("set -e")
                        continue
                    lines.append(line)

    # Start SSH and enable on boot
    if os_name == "debian":
        lines.append("service ssh start")
    else:  # alpine
        lines.append("rc-update add sshd default")
        lines.append("rc-service sshd start")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Container creation
# ---------------------------------------------------------------------------

def create_container(name, os_name=None, cpus=None, ram=None, disk=None,
                     init_scripts=None, autostart=False, password=None, start=True):
    """Create a new LXC container. Returns (success, password) tuple."""
    if container_exists(name):
        print(f"Container '{name}' already exists.")
        return False, None

    cfg = load_config()
    defaults = cfg.get("defaults", DEFAULT_CONFIG["defaults"])

    os_name = os_name or defaults.get("os", "debian")
    cpus = cpus if cpus is not None else defaults.get("cpus", 1)
    ram = ram if ram is not None else defaults.get("ram", 512)
    disk = disk if disk is not None else defaults.get("disk", 5)

    arch = host_arch()
    vcpus = resolve_resource(cpus, host_cpus())
    ram_mb = resolve_resource(ram, host_ram_mb())
    disk_gb = resolve_resource(disk, host_disk_gb())

    # Generate random password if not provided
    if password is None:
        import secrets
        import string
        alphabet = string.ascii_letters + string.digits
        password = ''.join(secrets.choice(alphabet) for _ in range(12))

    print(f"Creating container '{name}': os={os_name} vcpus={vcpus} ram={ram_mb}MB disk={disk_gb}GB")

    # Get LXC template name
    template = LXC_TEMPLATES.get(os_name)
    if not template:
        print(f"Error: unsupported OS '{os_name}'", file=sys.stderr)
        return False, None

    # Create container with template
    try:
        if os_name == "debian":
            lxc(f"lxc-create -n {name} -t download -- -d debian -r bullseye -a {arch}")
        else:  # alpine
            lxc(f"lxc-create -n {name} -t download -- -d alpine -r 3.20 -a {arch}")
    except RuntimeError as e:
        print(f"Failed to create container: {e}", file=sys.stderr)
        return False, None

    # Set resource limits
    try:
        set_resource_limits(name, vcpus, ram_mb)
    except Exception as e:
        print(f"Warning: Failed to set resource limits: {e}", file=sys.stderr)

    # Configure autostart
    if autostart:
        config_path = lxc_config_path(name)
        with open(config_path, 'a') as f:
            f.write("lxc.start.auto = 1\n")

    # Start container
    if start:
        try:
            lxc(f"lxc-start -n {name}")
            time.sleep(3)  # Wait for container to boot
        except RuntimeError as e:
            print(f"Failed to start container: {e}", file=sys.stderr)
            lxc(f"lxc-destroy -n {name}", check=False)
            return False, None

    # Generate and run setup script
    setup_script = generate_setup_script(name, os_name, init_scripts, password)

    d = container_dir(name)
    os.makedirs(d, exist_ok=True)
    setup_script_path = os.path.join(d, "setup.sh")
    with open(setup_script_path, "w") as f:
        f.write(setup_script)

    # Copy and execute setup script
    try:
        lxc_rootfs = os.path.join(LXC_PATH, name, "rootfs")
        run(f"sudo cp {setup_script_path} {lxc_rootfs}/tmp/setup.sh")

        # Wait for network to be ready (especially for DHCP)
        print("Waiting for network to be ready...")
        time.sleep(5)

        # Verify container has network connectivity before running setup
        max_retries = 6
        for i in range(max_retries):
            try:
                lxc(f"lxc-attach -n {name} -- ping -c 1 -W 2 8.8.8.8", check=True)
                break
            except:
                if i < max_retries - 1:
                    time.sleep(2)
                else:
                    print("Warning: Network connectivity check failed, proceeding anyway...")

        lxc(f"lxc-attach -n {name} -- sh /tmp/setup.sh")
    except RuntimeError as e:
        print(f"Failed to setup container: {e}", file=sys.stderr)
        lxc(f"lxc-destroy -n {name}", check=False)
        return False, None

    # Save metadata
    meta = {
        "name": name,
        "os": os_name,
        "arch": arch,
        "vcpus": vcpus,
        "ram_mb": ram_mb,
        "disk_gb": disk_gb,
        "autostart": autostart,
        "init_scripts": init_scripts,
    }
    save_meta(name, meta)

    if not start:
        lxc(f"lxc-stop -n {name}", check=False)
        print(f"Container '{name}' created (not started).")
    else:
        print(f"Container '{name}' created and started.")

    return True, password


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_create(args):
    """Create a new container and show SSH credentials."""
    # Resolve init scripts
    init_scripts = []
    if args.script:
        script_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
        for script_name in args.script.split(","):
            script_name = script_name.strip()
            builtin_path = os.path.join(script_dir, f"{script_name}.sh")
            if os.path.exists(builtin_path):
                init_scripts.append(builtin_path)
            elif os.path.exists(script_name):
                init_scripts.append(script_name)
            else:
                print(f"Warning: Script not found: {script_name}")

    success, password = create_container(
        args.name, os_name=args.os, cpus=args.cpus, ram=args.ram,
        disk=args.disk, init_scripts=init_scripts if init_scripts else None,
        autostart=getattr(args, "autostart", False),
        start=not args.no_start
    )

    if not success:
        return

    # Wait for IP if started
    if not args.no_start:
        print("\nWaiting for IP address...")
        ip = container_ip(args.name, timeout=30)
        if not ip:
            print("Could not get container IP address. Check 'nox status' later.")
            return

        print(f"\n{'='*60}")
        print(f"Container '{args.name}' is ready!")
        print(f"{'='*60}")
        print(f"\nSSH Access (password shown once):")
        print(f"  ssh nox@{ip}")
        print(f"  Password: {password}")
        print(f"\nPasswordless access via nox:")
        print(f"  nox ssh {args.name}")
        print(f"{'='*60}\n")
    else:
        print(f"\nContainer '{args.name}' created but not started.")
        print(f"Start it with: nox start {args.name}")


def cmd_start(args):
    """Start an existing container."""
    if not container_exists(args.name):
        print(f"Container '{args.name}' does not exist. Create it first with: nox create {args.name}", file=sys.stderr)
        sys.exit(1)

    state = container_state(args.name)
    if state == "RUNNING":
        print(f"Container '{args.name}' is already running.")
    else:
        lxc(f"lxc-start -n {args.name}")
        print(f"Container '{args.name}' started.")


def cmd_stop(args):
    if not container_exists(args.name):
        print(f"Container '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)
    state = container_state(args.name)
    if state != "RUNNING":
        print(f"Container '{args.name}' is not running (state: {state}).")
        return
    lxc(f"lxc-stop -n {args.name}")
    print(f"Container '{args.name}' stopped.")


def cmd_restart(args):
    if not container_exists(args.name):
        print(f"Container '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)
    lxc(f"lxc-stop -n {args.name}", check=False)
    time.sleep(2)
    lxc(f"lxc-start -n {args.name}")
    print(f"Container '{args.name}' restarted.")


def cmd_delete(args):
    if not container_exists(args.name):
        d = container_dir(args.name)
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"Cleaned up local files for '{args.name}'.")
        else:
            print(f"Container '{args.name}' does not exist.", file=sys.stderr)
        return

    state = container_state(args.name)
    if state == "RUNNING":
        lxc(f"lxc-stop -n {args.name}")

    lxc(f"lxc-destroy -n {args.name}")
    d = container_dir(args.name)
    if os.path.exists(d):
        shutil.rmtree(d)
    print(f"Container '{args.name}' deleted.")


def cmd_list(args):
    r = lxc("lxc-ls", check=False)
    if r.returncode != 0:
        print("Could not list containers. Is LXC installed?", file=sys.stderr)
        sys.exit(1)

    container_names = [n.strip() for n in r.stdout.split() if n.strip()]

    if not container_names:
        print("No containers found.")
        return

    print(f"{'NAME':<20} {'STATE':<15} {'OS':<10} {'CPUS':<6} {'RAM':<8} {'DISK':<8} {'AUTOSTART':<10} {'IP'}")
    print("-" * 95)

    for name in container_names:
        state = container_state(name) or "UNKNOWN"

        meta = load_meta(name) or {}
        os_name = meta.get("os", "?")
        vcpus = meta.get("vcpus", "?")
        ram = meta.get("ram_mb", "?")
        disk_g = meta.get("disk_gb", "?")
        auto = meta.get("autostart", False)

        ip = ""
        if state == "RUNNING":
            ip = container_ip(name, timeout=1) or ""

        ram_str = f"{ram}MB" if ram != "?" else "?"
        disk_str = f"{disk_g}GB" if disk_g != "?" else "?"
        auto_str = "yes" if auto else "no"
        print(f"{name:<20} {state:<15} {os_name:<10} {vcpus:<6} {ram_str:<8} {disk_str:<8} {auto_str:<10} {ip}")


def cmd_status(args):
    if not container_exists(args.name):
        print(f"Container '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)

    meta = load_meta(args.name) or {}
    state = container_state(args.name)

    print(f"Name:      {args.name}")
    print(f"State:     {state}")
    print(f"OS:        {meta.get('os', '?')}")
    print(f"Arch:      {meta.get('arch', '?')}")
    print(f"vCPUs:     {meta.get('vcpus', '?')}")
    print(f"RAM:       {meta.get('ram_mb', '?')} MB")
    print(f"Disk:      {meta.get('disk_gb', '?')} GB")
    print(f"Autostart: {'yes' if meta.get('autostart') else 'no'}")

    if state == "RUNNING":
        ip = container_ip(args.name, timeout=5)
        print(f"IP:        {ip or 'waiting...'}")


def cmd_autostart(args):
    if not container_exists(args.name):
        print(f"Container '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)

    config_path = lxc_config_path(args.name)

    with open(config_path, 'r') as f:
        lines = f.readlines()

    # Remove old autostart line
    lines = [l for l in lines if 'lxc.start.auto' not in l]

    if args.enable:
        lines.append("lxc.start.auto = 1\n")
        meta = load_meta(args.name) or {}
        meta["autostart"] = True
        save_meta(args.name, meta)
        print(f"Autostart enabled for '{args.name}'.")
    elif args.disable:
        lines.append("lxc.start.auto = 0\n")
        meta = load_meta(args.name) or {}
        meta["autostart"] = False
        save_meta(args.name, meta)
        print(f"Autostart disabled for '{args.name}'.")
    else:
        print("Specify --enable or --disable.", file=sys.stderr)
        sys.exit(1)

    with open(config_path, 'w') as f:
        f.writelines(lines)


def cmd_ssh(args):
    if not container_exists(args.name):
        print(f"Container '{args.name}' does not exist. Create it first with: nox create {args.name}", file=sys.stderr)
        sys.exit(1)

    state = container_state(args.name)
    if state != "RUNNING":
        lxc(f"lxc-start -n {args.name}")
        print(f"Starting container '{args.name}'...")
        time.sleep(3)

    print(f"Waiting for IP address...")
    ip = container_ip(args.name, timeout=30)
    if not ip:
        print("Could not get container IP address.", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to {ip}...")
    ssh_cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=10",
        f"nox@{ip}",
    ]
    if args.ssh_command:
        ssh_cmd.extend(args.ssh_command)

    os.execvp("ssh", ssh_cmd)


def cmd_run(args):
    if not container_exists(args.name):
        print(f"Container '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)

    state = container_state(args.name)
    if state != "RUNNING":
        print(f"Container '{args.name}' is not running.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.script):
        print(f"Script not found: {args.script}", file=sys.stderr)
        sys.exit(1)

    ip = container_ip(args.name, timeout=30)
    if not ip:
        print("Could not get container IP address.", file=sys.stderr)
        sys.exit(1)

    ssh_opts = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

    # SCP script to container
    run(f"scp {ssh_opts} {args.script} nox@{ip}:/tmp/nox-run.sh")
    # Execute it
    run(f"ssh {ssh_opts} nox@{ip} 'chmod +x /tmp/nox-run.sh && /tmp/nox-run.sh'", capture=False)


def cmd_images(args):
    arch = host_arch()
    print(f"Available images (arch: {arch}):\n")
    for os_name, template in LXC_TEMPLATES.items():
        print(f"  {os_name:<10} {template}")
    print()


def cmd_config(args):
    cfg = load_config()

    if args.config_action == "get":
        if args.key:
            parts = args.key.split(".")
            val = cfg
            for p in parts:
                if isinstance(val, dict):
                    val = val.get(p)
                else:
                    val = None
                    break
            print(json.dumps(val, indent=2) if isinstance(val, (dict, list)) else val)
        else:
            print(json.dumps(cfg, indent=2))

    elif args.config_action == "set":
        if not args.key or args.value is None:
            print("Usage: nox config set <key> <value>", file=sys.stderr)
            sys.exit(1)
        parts = args.key.split(".")
        obj = cfg
        for p in parts[:-1]:
            if p not in obj:
                obj[p] = {}
            obj = obj[p]
        val = args.value
        try:
            val = int(val)
        except ValueError:
            try:
                val = float(val)
            except ValueError:
                pass
        obj[parts[-1]] = val
        save_config(cfg)
        print(f"Set {args.key} = {val}")


def cmd_install_deps(args):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "install.sh")
    if os.path.exists(script):
        os.execvp("bash", ["bash", script])
    else:
        print("install.sh not found. Run it manually or place it next to nox.py.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(prog="nox", description="LXC Container Manager")
    sub = parser.add_subparsers(dest="command")

    # create
    p = sub.add_parser("create", help="Create a new container")
    p.add_argument("name")
    p.add_argument("--os", choices=["alpine", "debian"], default=None)
    p.add_argument("--cpus", type=float, default=None)
    p.add_argument("--ram", type=float, default=None)
    p.add_argument("--disk", type=float, default=None)
    p.add_argument("--script", default=None, help="Comma-separated list of scripts (docker,tailscale,claude) or full paths")
    p.add_argument("--autostart", action="store_true")
    p.add_argument("--no-start", action="store_true", help="Create but don't start container")

    # start
    p = sub.add_parser("start", help="Start an existing container")
    p.add_argument("name")

    # stop
    p = sub.add_parser("stop", help="Stop container")
    p.add_argument("name")

    # restart
    p = sub.add_parser("restart", help="Restart container")
    p.add_argument("name")

    # delete
    p = sub.add_parser("delete", help="Delete container")
    p.add_argument("name")

    # list
    sub.add_parser("list", aliases=["ls"], help="List all containers")

    # status
    p = sub.add_parser("status", help="Show container details")
    p.add_argument("name")

    # autostart
    p = sub.add_parser("autostart", help="Manage container autostart")
    p.add_argument("name")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--enable", action="store_true")
    g.add_argument("--disable", action="store_true")

    # ssh
    p = sub.add_parser("ssh", help="SSH into container (creates+starts if needed)")
    p.add_argument("name")
    p.add_argument("ssh_command", nargs="*", default=None)

    # run
    p = sub.add_parser("run", help="Run script on container via SSH")
    p.add_argument("name")
    p.add_argument("--script", required=True)

    # images
    p = sub.add_parser("images", help="List available LXC templates")

    # config
    p = sub.add_parser("config", help="Manage nox config")
    p.add_argument("config_action", choices=["get", "set"])
    p.add_argument("key", nargs="?", default=None)
    p.add_argument("value", nargs="?", default=None)

    # install-deps
    sub.add_parser("install-deps", help="Install LXC dependencies")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    ensure_dirs()

    commands = {
        "create": cmd_create,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "delete": cmd_delete,
        "list": cmd_list,
        "ls": cmd_list,
        "status": cmd_status,
        "autostart": cmd_autostart,
        "ssh": cmd_ssh,
        "run": cmd_run,
        "images": cmd_images,
        "config": cmd_config,
        "install-deps": cmd_install_deps,
    }

    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
