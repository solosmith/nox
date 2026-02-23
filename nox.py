#!/usr/bin/env python3
"""nox - Lightweight VM Manager using libvirt/KVM"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
import tempfile
import secrets
import string

def get_version():
    """Read version from VERSION file."""
    locations = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION"),
        "/usr/local/bin/VERSION",
    ]
    for version_file in locations:
        try:
            with open(version_file, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            continue
    return "unknown"

VERSION = get_version()
NOX_DIR = os.path.expanduser("~/.nox")
VMS_DIR = os.path.join(NOX_DIR, "vms")
IMAGES_DIR = os.path.join(NOX_DIR, "images")
BACKUPS_DIR = os.path.join(NOX_DIR, "backups")
CONFIG_FILE = os.path.join(NOX_DIR, "config.json")

DEFAULT_CONFIG = {
    "defaults": {"os": "debian", "cpus": 1, "ram": 512, "disk": 5},
    "env": {},
}

# OS image URLs (cloud images with cloud-init support)
OS_IMAGES = {
    "debian": {
        "url": "https://cloud.debian.org/images/cloud/bullseye/latest/debian-11-genericcloud-arm64.qcow2",
        "url_amd64": "https://cloud.debian.org/images/cloud/bullseye/latest/debian-11-genericcloud-amd64.qcow2",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_dirs():
    os.makedirs(VMS_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(BACKUPS_DIR, exist_ok=True)

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
    if capture:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(f"Command failed: {cmd}\n{result.stderr}")
        return result
    else:
        result = subprocess.run(cmd, shell=True)
        if check and result.returncode != 0:
            raise RuntimeError(f"Command failed: {cmd}")
        return result

def virsh(cmd, check=True):
    """Run a virsh command."""
    return run(f"virsh --connect qemu:///system {cmd}", check=check, capture=True)

def vm_exists(name):
    """Check if VM exists."""
    result = virsh(f"dominfo {name}", check=False)
    return result.returncode == 0

def vm_state(name):
    """Get VM state."""
    result = virsh(f"domstate {name}", check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip()

def vm_dir(name):
    return os.path.join(VMS_DIR, name)

def meta_path(name):
    return os.path.join(vm_dir(name), "meta.json")

def load_meta(name):
    p = meta_path(name)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None

def save_meta(name, meta):
    d = vm_dir(name)
    os.makedirs(d, exist_ok=True)
    with open(meta_path(name), "w") as f:
        json.dump(meta, f, indent=2)

def vm_ip(name, timeout=60):
    """Get VM IP address using qemu-guest-agent."""
    deadline = time.time() + timeout

    while time.time() < deadline:
        result = virsh(f"domifaddr {name} --source agent", check=False)
        if result.returncode == 0:
            stdout = result.stdout if isinstance(result.stdout, str) else result.stdout.decode('utf-8')
            for line in stdout.splitlines():
                if "ipv4" in line.lower() and "127.0.0.1" not in line:
                    parts = line.split()
                    for part in parts:
                        if "/" in part and not part.startswith("127."):
                            return part.split("/")[0]

        time.sleep(2)

    return None

def generate_password():
    """Generate random password."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(12))

# ---------------------------------------------------------------------------
# Cloud-init generation
# ---------------------------------------------------------------------------

def generate_cloud_init(name, password, ssh_key=None, os_name="debian"):
    """Generate cloud-init user-data."""
    # Find SSH public key
    if not ssh_key:
        for keyfile in ["id_ed25519.pub", "id_rsa.pub"]:
            p = os.path.expanduser(f"~/.ssh/{keyfile}")
            if os.path.exists(p):
                with open(p) as f:
                    ssh_key = f.read().strip()
                break

    user_data = f"""#cloud-config
hostname: {name}
fqdn: {name}.local
manage_etc_hosts: true

users:
  - name: nox
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: sudo
    shell: /bin/bash
    lock_passwd: false
    passwd: {password}
    ssh_authorized_keys:
      - {ssh_key if ssh_key else ''}

ssh_pwauth: true

package_update: true
package_upgrade: false
packages:
  - qemu-guest-agent

runcmd:
  - echo 'nox:{password}' | chpasswd
  - systemctl enable qemu-guest-agent
  - systemctl start qemu-guest-agent
  - systemctl enable ssh
  - systemctl start ssh
"""

    meta_data = f"""instance-id: {name}
local-hostname: {name}
"""

    return user_data, meta_data

# ---------------------------------------------------------------------------
# VM creation
# ---------------------------------------------------------------------------

def create_vm(name, os_name=None, cpus=None, ram=None, disk=None,
              autostart=False, password=None, start=True, network="nox-net"):
    """Create a new VM."""
    if vm_exists(name):
        print(f"VM '{name}' already exists.")
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

    if password is None:
        password = generate_password()

    print(f"Creating VM '{name}': os={os_name} vcpus={vcpus} ram={ram_mb}MB disk={disk_gb}GB")

    # Create VM directory
    vm_path = vm_dir(name)
    os.makedirs(vm_path, exist_ok=True)

    # Download cloud image to shared cache
    os_info = OS_IMAGES.get(os_name)
    if not os_info:
        raise RuntimeError(f"Unknown OS: {os_name}")

    # Select URL based on architecture
    if arch == "arm64":
        image_url = os_info.get("url")
    else:
        image_url = os_info.get("url_amd64")

    if not image_url:
        raise RuntimeError(f"No image URL for {os_name} on {arch}")

    # Use shared image cache
    image_filename = f"{os_name}-{arch}.qcow2"
    base_image = os.path.join(IMAGES_DIR, image_filename)

    if not os.path.exists(base_image):
        print(f"Downloading {os_name} cloud image...")
        run(f"curl -fsSL {image_url} -o {base_image}")
    else:
        print(f"Using cached {os_name} cloud image")

    # Create disk image from base
    disk_path = os.path.join(vm_path, f"{name}.qcow2")
    run(f"qemu-img create -f qcow2 -F qcow2 -b {base_image} {disk_path} {disk_gb}G")

    # Generate cloud-init
    user_data, meta_data = generate_cloud_init(name, password, os_name=os_name)
    user_data_path = os.path.join(vm_path, "user-data")
    meta_data_path = os.path.join(vm_path, "meta-data")

    with open(user_data_path, "w") as f:
        f.write(user_data)
    with open(meta_data_path, "w") as f:
        f.write(meta_data)

    # Create cloud-init ISO
    cloud_init_iso = os.path.join(vm_path, "cloud-init.iso")
    run(f"genisoimage -output {cloud_init_iso} -volid cidata -joliet -rock {user_data_path} {meta_data_path}")

    # Create VM with virt-install
    cmd = f"""virt-install \\
        --connect qemu:///system \\
        --name {name} \\
        --memory {ram_mb} \\
        --vcpus {vcpus} \\
        --cpu host-passthrough \\
        --disk {disk_path},format=qcow2,bus=virtio,cache=writeback,io=threads \\
        --disk {cloud_init_iso},device=cdrom \\
        --os-variant generic \\
        --network network={network},model=virtio \\
        --graphics none \\
        --console pty,target_type=serial \\
        --import \\
        --noautoconsole"""

    if not start:
        cmd += " --noreboot"

    try:
        run(cmd)
    except RuntimeError as e:
        print(f"Failed to create VM: {e}", file=sys.stderr)
        shutil.rmtree(vm_path, ignore_errors=True)
        return False, None

    # Configure autostart
    if autostart:
        virsh(f"autostart {name}")

    # Save metadata
    meta = {
        "name": name,
        "os": os_name,
        "arch": arch,
        "vcpus": vcpus,
        "ram_mb": ram_mb,
        "disk_gb": disk_gb,
        "autostart": autostart,
    }
    save_meta(name, meta)

    if not start:
        print(f"VM '{name}' created (not started).")
    else:
        print(f"VM '{name}' created and starting...")

    return True, password

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_create(args):
    """Create a new VM and show SSH credentials."""
    # Use nox-net network (bridged to br0)
    network = "nox-net"

    success, password = create_vm(
        args.name, os_name=args.os, cpus=args.cpus, ram=args.ram,
        disk=args.disk, autostart=not getattr(args, "no_autostart", False),
        start=not args.no_start, network=network
    )

    if not success:
        return

    # Wait for IP if started
    if not args.no_start:
        print("\nWaiting for VM to boot and get IP address...")
        ip = vm_ip(args.name, timeout=180)

        print(f"\n{'='*60}")
        print(f"VM '{args.name}' is ready!")
        print(f"{'='*60}")
        print(f"\nSSH Access (password shown once):")
        print(f"  Password: {password}")
        if ip:
            print(f"  Command: ssh nox@{ip}")
        else:
            print(f"  IP not detected yet. Use 'nox list' to find it, then:")
            print(f"  Command: ssh nox@<IP_ADDRESS>")
        print(f"\nPasswordless access from host:")
        print(f"  nox ssh {args.name}")
        print(f"\nIMPORTANT: Save this password - it won't be shown again!")
        print(f"{'='*60}")

def cmd_start(args):
    if not vm_exists(args.name):
        print(f"VM '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)
    virsh(f"start {args.name}")
    print(f"VM '{args.name}' started.")

def cmd_stop(args):
    if not vm_exists(args.name):
        print(f"VM '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)
    virsh(f"shutdown {args.name}")
    print(f"VM '{args.name}' shutting down.")

def cmd_restart(args):
    if not vm_exists(args.name):
        print(f"VM '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)
    virsh(f"reboot {args.name}")
    print(f"VM '{args.name}' restarted.")

def cmd_delete(args):
    if not vm_exists(args.name):
        d = vm_dir(args.name)
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"Cleaned up local files for '{args.name}'.")
        else:
            print(f"VM '{args.name}' does not exist.", file=sys.stderr)
        return

    state = vm_state(args.name)
    if state == "running":
        virsh(f"destroy {args.name}")

    virsh(f"undefine {args.name} --nvram --remove-all-storage")
    d = vm_dir(args.name)
    if os.path.exists(d):
        shutil.rmtree(d)
    print(f"VM '{args.name}' deleted.")

def cmd_list(args):
    result = virsh("list --all", check=False)
    if result.returncode != 0:
        print("Could not list VMs. Is libvirt installed?", file=sys.stderr)
        sys.exit(1)

    # Parse virsh list output
    vm_names = []
    for line in result.stdout.splitlines()[2:]:  # Skip header
        parts = line.split()
        if len(parts) >= 2:
            vm_names.append(parts[1])

    if not vm_names:
        print("No VMs found.")
        return

    print(f"{'NAME':<20} {'STATE':<15} {'OS':<10} {'CPUS':<6} {'RAM':<8} {'DISK':<8} {'AUTOSTART':<10} {'IP'}")
    print("-" * 95)

    for name in vm_names:
        state = vm_state(name) or "UNKNOWN"

        meta = load_meta(name) or {}
        os_name = meta.get("os", "?")
        vcpus = meta.get("vcpus", "?")
        ram = meta.get("ram_mb", "?")
        disk_g = meta.get("disk_gb", "?")
        auto = meta.get("autostart", False)

        ip = ""
        if state == "running":
            ip = vm_ip(name, timeout=1) or ""

        ram_str = f"{ram}MB" if ram != "?" else "?"
        disk_str = f"{disk_g}GB" if disk_g != "?" else "?"
        auto_str = "yes" if auto else "no"

        print(f"{name:<20} {state:<15} {os_name:<10} {vcpus:<6} {ram_str:<8} {disk_str:<8} {auto_str:<10} {ip}")

def cmd_ssh(args):
    if not vm_exists(args.name):
        print(f"VM '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)

    state = vm_state(args.name)
    if state != "running":
        print(f"VM '{args.name}' is not running. Start it with: nox start {args.name}", file=sys.stderr)
        sys.exit(1)

    ip = vm_ip(args.name, timeout=10)
    if not ip:
        print(f"Could not get IP for VM '{args.name}'", file=sys.stderr)
        sys.exit(1)

    ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", f"nox@{ip}"]
    if args.ssh_command:
        ssh_cmd.extend(args.ssh_command)

    os.execvp("ssh", ssh_cmd)

def cmd_status(args):
    if not vm_exists(args.name):
        print(f"VM '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)

    result = virsh(f"dominfo {args.name}")
    print(result.stdout)

def cmd_passwd(args):
    """Change SSH password for a VM."""
    if not vm_exists(args.name):
        print(f"VM '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)

    state = vm_state(args.name)
    if state != "running":
        print(f"VM '{args.name}' is not running. Start it with: nox start {args.name}", file=sys.stderr)
        sys.exit(1)

    print(f"Generating new password for VM '{args.name}'...")
    ip = vm_ip(args.name, timeout=10)
    if not ip:
        print(f"Could not get IP for VM '{args.name}'", file=sys.stderr)
        sys.exit(1)

    # Generate new password
    new_password = generate_password()

    # Change password via SSH
    ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null nox@{ip} \"echo 'nox:{new_password}' | sudo chpasswd\""
    
    try:
        run(ssh_cmd)
        print(f"\n{'='*60}")
        print(f"Password changed successfully for VM '{args.name}'!")
        print(f"{'='*60}")
        print(f"\nNew SSH Password (shown once):")
        print(f"  Password: {new_password}")
        print(f"  Command: ssh nox@{ip}")
        print(f"\nIMPORTANT: Save this password - it won't be shown again!")
        print(f"{'='*60}")
    except RuntimeError as e:
        print(f"Failed to change password: {e}", file=sys.stderr)
        sys.exit(1)

def cmd_resize(args):
    """Resize VM resources (CPUs, RAM, or disk)."""
    if not vm_exists(args.name):
        print(f"VM '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)

    state = vm_state(args.name)
    meta = load_meta(args.name)
    if not meta:
        print(f"Could not load metadata for VM '{args.name}'", file=sys.stderr)
        sys.exit(1)

    vm_path = vm_dir(args.name)
    disk_path = os.path.join(vm_path, f"{args.name}.qcow2")

    # Handle CPU resize
    if args.cpus is not None:
        vcpus = resolve_resource(args.cpus, host_cpus())
        print(f"Resizing CPUs to {vcpus}...")
        
        # Set maximum vCPUs (requires VM to be shut off)
        if state == "running":
            print("Note: Setting maximum vCPUs requires VM shutdown. Stopping VM...")
            virsh(f"shutdown {args.name}")
            # Wait for shutdown
            for _ in range(30):
                if vm_state(args.name) == "shut off":
                    break
                time.sleep(1)
        
        virsh(f"setvcpus {args.name} {vcpus} --maximum --config")
        virsh(f"setvcpus {args.name} {vcpus} --config")
        meta["vcpus"] = vcpus
        print(f"✓ CPUs updated to {vcpus}")
        
        if state == "running":
            print("Restarting VM...")
            virsh(f"start {args.name}")

    # Handle RAM resize
    if args.ram is not None:
        ram_mb = resolve_resource(args.ram, host_ram_mb())
        ram_kb = ram_mb * 1024
        print(f"Resizing RAM to {ram_mb}MB...")
        
        if state == "running":
            print("Note: RAM resize requires VM shutdown. Stopping VM...")
            virsh(f"shutdown {args.name}")
            # Wait for shutdown
            for _ in range(30):
                if vm_state(args.name) == "shut off":
                    break
                time.sleep(1)
        
        virsh(f"setmaxmem {args.name} {ram_kb} --config")
        virsh(f"setmem {args.name} {ram_kb} --config")
        meta["ram_mb"] = ram_mb
        print(f"✓ RAM updated to {ram_mb}MB")
        
        if state == "running":
            print("Restarting VM...")
            virsh(f"start {args.name}")

    # Handle disk resize
    if args.disk is not None:
        disk_gb = resolve_resource(args.disk, host_disk_gb())
        current_disk = meta.get("disk_gb", 0)
        
        if disk_gb <= current_disk:
            print(f"Error: New disk size ({disk_gb}GB) must be larger than current size ({current_disk}GB)", file=sys.stderr)
            print("Disk shrinking is not supported.", file=sys.stderr)
            sys.exit(1)
        
        print(f"Expanding disk from {current_disk}GB to {disk_gb}GB...")
        
        # Resize the qcow2 image
        run(f"qemu-img resize {disk_path} {disk_gb}G")
        
        # If VM is running, use virsh blockresize
        if state == "running":
            virsh(f"blockresize {args.name} {disk_path} {disk_gb}G")
        
        meta["disk_gb"] = disk_gb
        print(f"✓ Disk expanded to {disk_gb}GB")
        print("Note: You may need to resize the filesystem inside the VM:")
        print("  sudo growpart /dev/vda 1")
        print("  sudo resize2fs /dev/vda1")

    # Save updated metadata
    save_meta(args.name, meta)
    
    print(f"\n✓ VM '{args.name}' resized successfully!")
    if state == "running" and (args.cpus is not None or args.ram is not None):
        print(f"VM state: running")
    elif state == "shut off":
        print(f"VM state: shut off (use 'nox start {args.name}' to start)")


def cmd_backup(args):
    """Backup a VM."""
    if not vm_exists(args.name):
        print(f"VM '{args.name}' does not exist.", file=sys.stderr)
        sys.exit(1)

    state = vm_state(args.name)
    was_running = state == "running"
    
    # Stop VM if running for consistent backup
    if was_running:
        print(f"Stopping VM '{args.name}' for backup...")
        virsh(f"shutdown {args.name}")
        # Wait for shutdown
        for _ in range(30):
            if vm_state(args.name) == "shut off":
                break
            time.sleep(1)
        else:
            print("Warning: VM did not shut down gracefully, forcing shutdown...")
            virsh(f"destroy {args.name}")
            time.sleep(2)

    # Create backup directory
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_name = f"{args.name}_{timestamp}"
    backup_path = os.path.join(BACKUPS_DIR, backup_name)
    os.makedirs(backup_path, exist_ok=True)

    print(f"Creating backup '{backup_name}'...")

    vm_path = vm_dir(args.name)
    disk_path = os.path.join(vm_path, f"{args.name}.qcow2")

    try:
        # Backup disk image
        print("Backing up disk image...")
        backup_disk = os.path.join(backup_path, f"{args.name}.qcow2")
        run(f"cp {disk_path} {backup_disk}")

        # Backup metadata
        meta = load_meta(args.name)
        if meta:
            backup_meta = os.path.join(backup_path, "meta.json")
            with open(backup_meta, "w") as f:
                json.dump(meta, f, indent=2)

        # Backup cloud-init files if they exist
        for filename in ["user-data", "meta-data", "cloud-init.iso"]:
            src = os.path.join(vm_path, filename)
            if os.path.exists(src):
                dst = os.path.join(backup_path, filename)
                shutil.copy2(src, dst)

        # Get VM XML definition
        result = virsh(f"dumpxml {args.name}")
        xml_path = os.path.join(backup_path, "domain.xml")
        xml_content = result.stdout if isinstance(result.stdout, str) else result.stdout.decode('utf-8')
        with open(xml_path, "w") as f:
            f.write(xml_content)

        # Create backup info file
        backup_info = {
            "vm_name": args.name,
            "backup_name": backup_name,
            "timestamp": timestamp,
            "was_running": was_running,
            "metadata": meta,
        }
        info_path = os.path.join(backup_path, "backup_info.json")
        with open(info_path, "w") as f:
            json.dump(backup_info, f, indent=2)

        print(f"✓ Backup created successfully: {backup_name}")
        print(f"  Location: {backup_path}")

    except Exception as e:
        print(f"Error creating backup: {e}", file=sys.stderr)
        shutil.rmtree(backup_path, ignore_errors=True)
        sys.exit(1)
    finally:
        # Restart VM if it was running
        if was_running:
            print(f"Restarting VM '{args.name}'...")
            virsh(f"start {args.name}")

def cmd_restore(args):
    """Restore a VM from backup."""
    backup_path = os.path.join(BACKUPS_DIR, args.backup_name)
    
    if not os.path.exists(backup_path):
        print(f"Backup '{args.backup_name}' does not exist.", file=sys.stderr)
        sys.exit(1)

    # Load backup info
    info_path = os.path.join(backup_path, "backup_info.json")
    if not os.path.exists(info_path):
        print(f"Invalid backup: missing backup_info.json", file=sys.stderr)
        sys.exit(1)

    with open(info_path) as f:
        backup_info = json.load(f)

    original_name = backup_info["vm_name"]
    restore_name = args.name if args.name else original_name

    # Check if VM already exists
    if vm_exists(restore_name):
        if not args.force:
            print(f"VM '{restore_name}' already exists. Use --force to overwrite.", file=sys.stderr)
            sys.exit(1)
        
        print(f"Deleting existing VM '{restore_name}'...")
        state = vm_state(restore_name)
        if state == "running":
            virsh(f"destroy {restore_name}")
        virsh(f"undefine {restore_name} --nvram --remove-all-storage", check=False)

    print(f"Restoring VM '{restore_name}' from backup '{args.backup_name}'...")

    # Create VM directory
    vm_path = vm_dir(restore_name)
    os.makedirs(vm_path, exist_ok=True)

    try:
        # Restore disk image
        print("Restoring disk image...")
        backup_disk = os.path.join(backup_path, f"{original_name}.qcow2")
        restore_disk = os.path.join(vm_path, f"{restore_name}.qcow2")
        run(f"cp {backup_disk} {restore_disk}")

        # Restore metadata
        backup_meta = os.path.join(backup_path, "meta.json")
        if os.path.exists(backup_meta):
            with open(backup_meta) as f:
                meta = json.load(f)
            meta["name"] = restore_name
            save_meta(restore_name, meta)

        # Restore cloud-init files
        for filename in ["user-data", "meta-data", "cloud-init.iso"]:
            src = os.path.join(backup_path, filename)
            if os.path.exists(src):
                dst = os.path.join(vm_path, filename)
                shutil.copy2(src, dst)

        # Restore VM from XML
        xml_path = os.path.join(backup_path, "domain.xml")
        if os.path.exists(xml_path):
            # Read and modify XML to update VM name and paths
            with open(xml_path) as f:
                xml_content = f.read()
            
            # Replace VM name and disk paths
            xml_content = xml_content.replace(f"<name>{original_name}</name>", f"<name>{restore_name}</name>")
            xml_content = xml_content.replace(f"{original_name}.qcow2", f"{restore_name}.qcow2")
            
            # Write modified XML to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as tmp:
                tmp.write(xml_content)
                tmp_xml = tmp.name
            
            try:
                virsh(f"define {tmp_xml}")
            finally:
                os.unlink(tmp_xml)

        print(f"✓ VM '{restore_name}' restored successfully!")
        
        if backup_info.get("was_running") and not args.no_start:
            print(f"Starting VM '{restore_name}'...")
            virsh(f"start {restore_name}")
        else:
            print(f"VM '{restore_name}' is ready. Use 'nox start {restore_name}' to start it.")

    except Exception as e:
        print(f"Error restoring backup: {e}", file=sys.stderr)
        shutil.rmtree(vm_path, ignore_errors=True)
        sys.exit(1)

def cmd_list_backups(args):
    """List all backups."""
    if not os.path.exists(BACKUPS_DIR):
        print("No backups found.")
        return

    backups = []
    for backup_name in os.listdir(BACKUPS_DIR):
        backup_path = os.path.join(BACKUPS_DIR, backup_name)
        if not os.path.isdir(backup_path):
            continue

        info_path = os.path.join(backup_path, "backup_info.json")
        if os.path.exists(info_path):
            with open(info_path) as f:
                info = json.load(f)
            backups.append((backup_name, info))

    if not backups:
        print("No backups found.")
        return

    print(f"{'BACKUP NAME':<40} {'VM NAME':<20} {'DATE':<20} {'SIZE'}")
    print("-" * 95)

    for backup_name, info in sorted(backups, key=lambda x: x[1].get("timestamp", ""), reverse=True):
        vm_name = info.get("vm_name", "?")
        timestamp = info.get("timestamp", "?")
        
        # Format timestamp
        if timestamp != "?":
            try:
                dt = time.strptime(timestamp, "%Y%m%d_%H%M%S")
                date_str = time.strftime("%Y-%m-%d %H:%M:%S", dt)
            except:
                date_str = timestamp
        else:
            date_str = "?"

        # Calculate backup size
        backup_path = os.path.join(BACKUPS_DIR, backup_name)
        total_size = 0
        for root, dirs, files in os.walk(backup_path):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.exists(fp):
                    total_size += os.path.getsize(fp)
        
        size_gb = total_size / (1024 ** 3)
        size_str = f"{size_gb:.2f}GB"

        print(f"{backup_name:<40} {vm_name:<20} {date_str:<20} {size_str}")

def cmd_update(args):
    """Update nox to the latest version from GitHub."""
    import tempfile

    GITHUB_RAW_URL = "https://raw.githubusercontent.com/solosmith/nox/main"

    print(f"Current version: {VERSION}")
    print("Checking for updates from GitHub...")

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            timestamp = int(time.time())

            if run("command -v curl >/dev/null 2>&1", check=False).returncode == 0:
                run(f"curl -H 'Cache-Control: no-cache' -fsSL '{GITHUB_RAW_URL}/VERSION?t={timestamp}' -o {tmpdir}/VERSION")
                run(f"curl -H 'Cache-Control: no-cache' -fsSL '{GITHUB_RAW_URL}/nox.py?t={timestamp}' -o {tmpdir}/nox.py")
            elif run("command -v wget >/dev/null 2>&1", check=False).returncode == 0:
                run(f"wget --no-cache -q '{GITHUB_RAW_URL}/VERSION?t={timestamp}' -O {tmpdir}/VERSION")
                run(f"wget --no-cache -q '{GITHUB_RAW_URL}/nox.py?t={timestamp}' -O {tmpdir}/nox.py")
            else:
                print("Error: Neither curl nor wget found.", file=sys.stderr)
                sys.exit(1)

            with open(f"{tmpdir}/VERSION", "r") as f:
                remote_version = f.read().strip()
                print(f"Latest version: {remote_version}")

                if remote_version == VERSION:
                    print("✓ Already up to date!")
                    return

            print("Installing updated version...")
            run(f"sudo cp {tmpdir}/nox.py /usr/local/bin/nox")
            run(f"sudo cp {tmpdir}/VERSION /usr/local/bin/VERSION")
            run("sudo chmod +x /usr/local/bin/nox")

            print(f"✓ nox updated successfully! ({VERSION} → {remote_version})")

        except Exception as e:
            print(f"Error updating nox: {e}", file=sys.stderr)
            sys.exit(1)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(prog="nox", description="Lightweight VM Manager")
    parser.add_argument("--version", action="version", version=f"nox {VERSION}")
    sub = parser.add_subparsers(dest="command")

    # create
    p = sub.add_parser("create", help="Create a new VM")
    p.add_argument("name")
    p.add_argument("--os", choices=["debian"], default=None)
    p.add_argument("--cpus", type=float, default=None)
    p.add_argument("--ram", type=float, default=None)
    p.add_argument("--disk", type=float, default=None)
    p.add_argument("--no-autostart", action="store_true", help="Disable autostart on boot")
    p.add_argument("--no-start", action="store_true", help="Create but don't start VM")

    # start
    p = sub.add_parser("start", help="Start a VM")
    p.add_argument("name")

    # stop
    p = sub.add_parser("stop", help="Stop VM")
    p.add_argument("name")

    # restart
    p = sub.add_parser("restart", help="Restart VM")
    p.add_argument("name")

    # delete
    p = sub.add_parser("delete", aliases=["rm"], help="Delete VM")
    p.add_argument("name")

    # list
    sub.add_parser("list", aliases=["ls"], help="List all VMs")

    # status
    p = sub.add_parser("status", help="Show VM details")
    p.add_argument("name")

    # ssh
    p = sub.add_parser("ssh", help="SSH into VM")
    p.add_argument("name")
    p.add_argument("ssh_command", nargs="*", default=None)

    # passwd
    p = sub.add_parser("passwd", help="Change SSH password for VM")
    p.add_argument("name")

    # resize
    p = sub.add_parser("resize", help="Resize VM resources")
    p.add_argument("name")
    p.add_argument("--cpus", type=float, default=None, help="New CPU count")
    p.add_argument("--ram", type=float, default=None, help="New RAM in MB")
    p.add_argument("--disk", type=float, default=None, help="New disk size in GB (can only expand)")

    # backup
    p = sub.add_parser("backup", help="Backup a VM")
    p.add_argument("name")

    # restore
    p = sub.add_parser("restore", help="Restore a VM from backup")
    p.add_argument("backup_name", help="Name of the backup to restore")
    p.add_argument("--name", default=None, help="New name for restored VM (default: original name)")
    p.add_argument("--force", action="store_true", help="Overwrite existing VM")
    p.add_argument("--no-start", action="store_true", help="Don't start VM after restore")

    # backups
    sub.add_parser("backups", help="List all backups")

    # update
    sub.add_parser("update", aliases=["up"], help="Update nox")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "create": cmd_create,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "delete": cmd_delete,
        "rm": cmd_delete,
        "list": cmd_list,
        "ls": cmd_list,
        "status": cmd_status,
        "ssh": cmd_ssh,
        "passwd": cmd_passwd,
        "resize": cmd_resize,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "backups": cmd_list_backups,
        "update": cmd_update,
        "up": cmd_update,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
