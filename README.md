# nox - Docker Container Manager

A simple, Lima-like container manager for Linux using Docker. Create isolated containers with SSH access, resource limits, and launch scripts.

## Features

- **Simple CLI** - Easy-to-use commands for container management
- **Docker-based** - Uses standard Docker (no snap required)
- **Network isolation** - Containers on isolated network with internet access
- **SSH access** - Password + SSH key authentication
- **Resource limits** - CPU and memory limits
- **Launch scripts** - Pre-built scripts for docker, tailscale, claude
- **Multi-OS support** - Debian and Alpine images
- **Autostart** - Optional container autostart on boot

## Installation

### 1. Install dependencies

```bash
cd /home/pi/nox
./install.sh
```

This will install Docker and Python3 on your system.

### 2. Install nox

```bash
sudo cp nox.py /usr/local/bin/nox
sudo chmod +x /usr/local/bin/nox
```

### 3. Log out and back in

This is required for Docker group membership to take effect.

## Usage

### Create a container

```bash
# Basic container
nox create mycontainer

# With specific OS and resources
nox create mycontainer --os debian --cpus 2 --ram 1024

# With launch scripts
nox create mycontainer --script docker
nox create mycontainer --script docker,tailscale,claude

# With autostart
nox create mycontainer --autostart
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

Pre-built scripts in `/home/pi/nox/scripts/`:

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

Containers are on an isolated Docker network (`nox-isolated`) with:
- Internet access via NAT
- Isolated from host LAN
- SSH access from host

## Examples

### Development container with Docker

```bash
nox create dev --os debian --cpus 2 --ram 2048 --script docker
nox ssh dev
```

### Lightweight Alpine container

```bash
nox create alpine-test --os alpine --cpus 0.5 --ram 256
nox ssh alpine-test
```

### Container with autostart

```bash
nox create service --autostart --script docker
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

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--os alpine\|debian` | Operating system | debian |
| `--cpus N` | CPU limit (fractional or absolute) | 1 |
| `--ram N` | RAM limit in MB (fractional or absolute) | 512 |
| `--disk N` | Disk size in GB (not enforced) | 5 |
| `--script SCRIPTS` | Comma-separated launch scripts | none |
| `--autostart` | Enable autostart on boot | false |
| `--no-start` | Create but don't start | false |

## Files

- `/home/pi/nox/nox.py` - Main CLI tool
- `/home/pi/nox/install.sh` - Dependency installer
- `/home/pi/nox/scripts/` - Launch scripts directory
- `~/.nox/containers/` - Container metadata
- `~/.nox/config.json` - User configuration

## Troubleshooting

### Container can't access internet

Check Docker network:
```bash
docker network inspect nox-isolated
```

### SSH connection refused

Wait a few seconds for SSH to start, then try again:
```bash
sleep 10 && nox ssh mycontainer
```

### Memory limits not working

Your kernel may not support cgroup memory limits. CPU limits will still work.

### Permission denied

Make sure you're in the docker group:
```bash
groups | grep docker
```

If not, log out and back in after running `install.sh`.

## License

MIT
