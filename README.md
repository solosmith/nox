# nox - LXC Container Manager

A simple, Lima-like container manager for Linux using LXC. Create isolated containers with SSH access, resource limits, and launch scripts.

## Features

- **Simple CLI** - Easy-to-use commands for container management
- **LXC-based** - Uses native LXC containers (no Docker required)
- **Dual networking modes** - Bridged networking on physical hardware, isolated on VMs
- **SSH access** - Password + SSH key authentication
- **Resource limits** - CPU and memory limits via cgroups
- **Launch scripts** - Pre-built scripts for docker, tailscale, claude
- **Multi-OS support** - Debian and Alpine images
- **Autostart** - Containers autostart on boot by default
- **Docker support** - Run Docker inside containers

## Requirements

- Linux system (Debian, Ubuntu, or Alpine)
- LXC installed
- Python 3
- Root/sudo access

**Note:** macOS is not supported. LXC requires Linux kernel features. For testing on macOS, deploy inside a Lima VM.

## Quick Installation

One-line install (recommended):

```bash
curl -fsSL https://raw.githubusercontent.com/solosmith/nox/main/install.sh | bash
```

Or manual installation:

```bash
git clone https://github.com/solosmith/nox.git
cd nox
sudo ./install.sh
```

## Updating

To update nox to the latest version:

```bash
nox update
```

## Quick Start

```bash
# Create a container
nox create mycontainer --os debian

# SSH into it (passwordless)
nox ssh mycontainer

# List containers
nox list

# Delete container
nox delete mycontainer
```

### Create a container

```bash
# Basic container (autostart enabled by default)
nox create mycontainer

# With specific OS and resources
nox create mycontainer --os debian --cpus 2 --ram 1024

# With launch scripts
nox create mycontainer --script docker
nox create mycontainer --script docker,tailscale,claude

# Disable autostart
nox create mycontainer --no-autostart
```

### SSH into container

```bash
# Passwordless SSH (uses your SSH key)
nox ssh mycontainer

# Run a command
nox ssh mycontainer -- uname -a
```

### Manage containers

```bash
# List all containers
nox list

# Show container details
nox status mycontainer

# Start/stop/restart
nox start mycontainer
nox stop mycontainer
nox restart mycontainer

# Delete container
nox delete mycontainer
```

### Configuration

```bash
# View config
nox config get

# Set defaults
nox config set defaults.os debian
nox config set defaults.cpus 2
nox config set defaults.ram 512

# Set environment variables (applied to all containers)
nox config set env.MY_VAR value
```

## Resource Limits

### Fractional resources

Use values <= 1.0 to specify fraction of host resources:

```bash
# 50% of host CPUs
nox create mycontainer --cpus 0.5

# 25% of host RAM
nox create mycontainer --ram 0.25
```

### Absolute resources

Use values > 1.0 to specify absolute amounts:

```bash
# 4 CPUs
nox create mycontainer --cpus 4

# 2048 MB RAM
nox create mycontainer --ram 2048
```

## Launch Scripts

Pre-built scripts in `scripts/`:

- **docker.sh** - Installs Docker inside container
- **tailscale.sh** - Installs Tailscale client
- **claude.sh** - Installs Claude Code CLI

### Using launch scripts

```bash
# Single script
nox create mycontainer --script docker

# Multiple scripts (comma-separated)
nox create mycontainer --script docker,tailscale

# Custom script (full path)
nox create mycontainer --script /path/to/script.sh
```

## Network

### Physical Hardware (Bridged Networking)
On physical machines, containers get local network IPs from your router:
- Accessible from any device on your LAN
- Can SSH directly: `ssh nox@<container-ip>`
- Full network connectivity like a separate device

### Virtual Machines (Isolated Networking)
In VMs (Lima, etc.), containers use isolated network (10.0.3.x):
- Internet access via NAT
- Isolated from host LAN
- SSH from host only

The system automatically detects the environment and configures networking appropriately.

## Examples

### Development container with Docker

```bash
nox create dev --os debian --cpus 2 --ram 2048 --script docker
nox ssh dev

# Inside container, Docker is ready to use
docker run hello-world
```

### Lightweight Alpine container

```bash
nox create alpine-test --os alpine --cpus 0.5 --ram 256
nox ssh alpine-test
```

### Container without autostart

```bash
nox create temp --no-autostart
```

### Running Docker inside nox container

```bash
# Create container with Docker
nox create docker-host --script docker

# SSH into it
nox ssh docker-host

# Run Docker containers inside
docker run -d -p 8080:80 nginx
```

## Commands Reference

| Command | Description |
|---------|-------------|
| `nox create NAME [OPTIONS]` | Create a new container |
| `nox start NAME` | Start a container |
| `nox stop NAME` | Stop a container |
| `nox restart NAME` | Restart a container |
| `nox delete NAME` | Delete a container |
| `nox list` | List all containers |
| `nox status NAME` | Show container details |
| `nox ssh NAME [COMMAND]` | SSH into container |
| `nox autostart NAME --enable/--disable` | Manage autostart |
| `nox config get/set KEY [VALUE]` | Manage configuration |
| `nox images` | List available images |
| `nox update` | Update nox to latest version |

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--os alpine\|debian` | Operating system | debian |
| `--cpus N` | CPU limit (fractional or absolute) | 1 |
| `--ram N` | RAM limit in MB (fractional or absolute) | 512 |
| `--disk N` | Disk size in GB (informational) | 5 |
| `--script SCRIPTS` | Comma-separated launch scripts | none |
| `--no-autostart` | Disable autostart on boot | false |
| `--no-start` | Create but don't start | false |

## Files

- `nox.py` - Main CLI tool
- `install.sh` - Dependency installer
- `scripts/` - Launch scripts directory
- `~/.nox/containers/` - Container metadata
- `~/.nox/config.json` - User configuration
- `/var/lib/lxc/` - LXC container storage

## Troubleshooting

### Container can't access internet

Check LXC bridge:
```bash
sudo lxc-ls --fancy
ip addr show lxcbr0
```

Restart LXC networking:
```bash
sudo systemctl restart lxc-net  # Debian/Ubuntu
sudo service lxc restart         # Alpine
```

### SSH connection refused

Wait a few seconds for SSH to start, then try again:
```bash
sleep 10 && nox ssh mycontainer
```

### Permission denied

Make sure you're in the lxc group:
```bash
groups | grep lxc
```

If not, log out and back in after running `install.sh`.

### Container creation fails

Check LXC is properly installed:
```bash
sudo lxc-checkconfig
```

Ensure templates are available:
```bash
ls /usr/share/lxc/templates/
```

### Memory limits not working

Your system may not have the memory cgroup controller enabled. Check:
```bash
cat /sys/fs/cgroup/cgroup.controllers
```

If `memory` is not listed, memory limits will be skipped automatically. CPU limits will still work.

### Containers not accessible from LAN

If you're on physical hardware and containers aren't getting local network IPs:
```bash
# Check bridge configuration
ip link show lxcbr0
brctl show

# Verify bridge is attached to physical interface
sudo brctl show lxcbr0
```

On virtual machines (Lima, etc.), containers use isolated networking by design.

## Testing on macOS

Since LXC requires Linux, test on macOS using Lima:

```bash
# Install Lima
brew install lima

# Create a Linux VM
limactl start --name=nox-test template://debian

# SSH into the VM
lima nox-test

# Inside the VM, clone and install nox
git clone <your-repo>
cd nox
./install.sh
sudo cp nox.py /usr/local/bin/nox
sudo chmod +x /usr/local/bin/nox

# Use nox normally
nox create test
nox ssh test
```

## Differences from Docker version

- Uses LXC instead of Docker
- Requires sudo for container operations
- Dual networking: bridged on hardware, isolated in VMs
- Resource limits via cgroups (both v1 and v2 supported)
- Container storage in `/var/lib/lxc/`
- More VM-like experience
- Autostart enabled by default
- Can run Docker inside containers

## License

MIT
