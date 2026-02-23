# nox - Lightweight VM Manager

A simple VM manager for Linux using libvirt/KVM. Create VMs with SSH access, resource management, and automated backups with S3 integration.

Current version: 1.0.0

## Features

- **Simple CLI** - Easy-to-use commands for VM management
- **KVM/libvirt-based** - Uses native virtualization
- **Live backups** - Zero-downtime backups with compression
- **S3 integration** - Auto-upload backups to S3-compatible storage
- **Interactive restore** - Arrow key selection for backup restoration
- **SSH access** - Password + SSH key authentication
- **Resource management** - Resize CPU, RAM, and disk on-the-fly
- **Password rotation** - Secure password generation and updates
- **Cloud-init** - Automated VM provisioning
- **Debian support** - Pre-configured Debian cloud images

## Requirements

- Linux system (Debian, Ubuntu, or similar)
- KVM/QEMU and libvirt installed
- Python 3
- Root/sudo access
- Optional: AWS CLI for S3 integration

**Note:** macOS is not supported. KVM requires Linux kernel features.

## Quick Installation

One-line install (recommended):

```bash
curl -fsSL https://raw.githubusercontent.com/solosmith/nox/main/install.sh | bash
```

Or manual installation:

```bash
git clone https://github.com/solosmith/nox.git
cd nox
sudo cp nox.py /usr/local/bin/nox
sudo chmod +x /usr/local/bin/nox
```

## Updating

To update nox to the latest version:

```bash
nox update
```

To check your current version:

```bash
nox --version
```

## Quick Start

```bash
# Create a VM
nox create myvm --cpus 2 --ram 1024 --disk 10

# SSH into it (passwordless)
nox ssh myvm

# List VMs
nox list

# Backup VM
nox backup myvm

# Delete VM
nox delete myvm
```

## VM Management

### Create a VM

```bash
# Basic VM (autostart enabled by default)
nox create myvm

# With specific resources
nox create myvm --os debian --cpus 2 --ram 1024 --disk 10

# Create without starting
nox create myvm --no-start

# Disable autostart
nox create myvm --no-autostart
```

### SSH into VM

```bash
# Passwordless SSH (uses your SSH key)
nox ssh myvm

# Run a command
nox ssh myvm -- uname -a
```

### Manage VMs

```bash
# List all VMs
nox list

# Show VM details
nox status myvm

# Start/stop/restart
nox start myvm
nox stop myvm
nox restart myvm

# Delete VM
nox delete myvm
# or
nox rm myvm
```

### Change SSH Password

```bash
# Generate and set new password
nox passwd myvm
```

The new password is displayed once - save it immediately!

## Resource Management

### Resize VM Resources

```bash
# Resize CPU
nox resize myvm --cpus 4

# Resize RAM
nox resize myvm --ram 2048

# Expand disk (cannot shrink)
nox resize myvm --disk 20

# Resize multiple resources
nox resize myvm --cpus 4 --ram 2048 --disk 20
```

**Note:** CPU and RAM changes require VM restart. Disk expansion works while VM is running.

### Fractional Resources

Use values <= 1.0 to specify fraction of host resources:

```bash
# 50% of host CPUs
nox create myvm --cpus 0.5

# 25% of host RAM
nox create myvm --ram 0.25
```

### Absolute Resources

Use values > 1.0 to specify absolute amounts:

```bash
# 4 CPUs
nox create myvm --cpus 4

# 2048 MB RAM
nox create myvm --ram 2048

# 20 GB disk
nox create myvm --disk 20
```

## Backup & Restore

### Create Backup

```bash
# Backup VM (live backup - no downtime)
nox backup myvm
```

Backups are:
- **Compressed** - Only used disk space is backed up
- **Live** - VM continues running during backup (uses snapshots)
- **Complete** - Includes disk, metadata, cloud-init, and VM config
- **S3-ready** - Auto-uploaded if S3 is configured

### List Backups

```bash
# List all backups (local + S3)
nox backups
```

### Restore from Backup

```bash
# Interactive restore (arrow keys to select)
nox restore

# Direct restore
nox restore myvm_20260224_120000

# Restore with new name
nox restore myvm_20260224_120000 --name newvm

# Force overwrite existing VM
nox restore myvm_20260224_120000 --force

# Restore without starting
nox restore myvm_20260224_120000 --no-start
```

## S3 Integration

### Configure S3

Edit `~/.nox/config.json`:

```json
{
  "defaults": {
    "os": "debian",
    "cpus": 1,
    "ram": 512,
    "disk": 5
  },
  "s3": {
    "enabled": true,
    "endpoint": "https://s3.amazonaws.com",
    "bucket": "my-backups",
    "access_key": "YOUR_ACCESS_KEY",
    "secret_key": "YOUR_SECRET_KEY",
    "region": "us-east-1"
  }
}
```

### S3-Compatible Services

Works with any S3-compatible storage:

**AWS S3:**
```json
{
  "endpoint": "https://s3.amazonaws.com",
  "region": "us-east-1"
}
```

**MinIO:**
```json
{
  "endpoint": "https://minio.example.com",
  "region": "us-east-1"
}
```

**DigitalOcean Spaces:**
```json
{
  "endpoint": "https://nyc3.digitaloceanspaces.com",
  "region": "nyc3"
}
```

**Backblaze B2:**
```json
{
  "endpoint": "https://s3.us-west-002.backblazeb2.com",
  "region": "us-west-002"
}
```

### How S3 Integration Works

1. **Backup** - After creating a backup, it's automatically uploaded to S3 as a compressed tarball
2. **List** - `nox backups` shows both local and S3 backups with `[Local]` or `[S3]` tags
3. **Restore** - When restoring from S3, the backup is downloaded automatically

## Commands Reference

| Command | Description |
|---------|-------------|
| `nox create NAME [OPTIONS]` | Create a new VM |
| `nox start NAME` | Start a VM |
| `nox stop NAME` | Stop a VM |
| `nox restart NAME` | Restart a VM |
| `nox delete NAME` | Delete a VM |
| `nox rm NAME` | Alias for delete |
| `nox list` | List all VMs |
| `nox ls` | Alias for list |
| `nox status NAME` | Show VM details |
| `nox ssh NAME [COMMAND]` | SSH into VM |
| `nox passwd NAME` | Change SSH password |
| `nox resize NAME [OPTIONS]` | Resize VM resources |
| `nox backup NAME` | Backup a VM |
| `nox restore [BACKUP]` | Restore VM (interactive if no backup specified) |
| `nox backups` | List all backups (local + S3) |
| `nox update` | Update nox to latest version |

## Options

### Create Options

| Option | Description | Default |
|--------|-------------|---------|
| `--os debian` | Operating system | debian |
| `--cpus N` | CPU count (fractional or absolute) | 1 |
| `--ram N` | RAM in MB (fractional or absolute) | 512 |
| `--disk N` | Disk size in GB | 5 |
| `--no-autostart` | Disable autostart on boot | false |
| `--no-start` | Create but don't start | false |

### Resize Options

| Option | Description |
|--------|-------------|
| `--cpus N` | New CPU count |
| `--ram N` | New RAM in MB |
| `--disk N` | New disk size in GB (expand only) |

### Restore Options

| Option | Description |
|--------|-------------|
| `--name NAME` | New name for restored VM |
| `--force` | Overwrite existing VM |
| `--no-start` | Don't start VM after restore |

## Files

- `nox.py` - Main CLI tool
- `~/.nox/vms/` - VM storage and metadata
- `~/.nox/images/` - Cached OS images
- `~/.nox/backups/` - Local backups
- `~/.nox/config.json` - User configuration

## Examples

### Development VM

```bash
# Create VM with 4 CPUs, 4GB RAM, 20GB disk
nox create dev --cpus 4 --ram 4096 --disk 20

# SSH into it
nox ssh dev

# Install software inside VM
sudo apt update && sudo apt install -y docker.io
```

### Backup Workflow

```bash
# Create and backup a VM
nox create prod --cpus 2 --ram 2048 --disk 20
nox backup prod

# List backups
nox backups

# Restore to new VM
nox restore prod_20260224_120000 --name prod-clone
```

### Resource Scaling

```bash
# Start small
nox create app --cpus 1 --ram 512 --disk 10

# Scale up as needed
nox resize app --cpus 4 --ram 4096 --disk 50
```

## Troubleshooting

### VM won't start

Check libvirt status:
```bash
sudo systemctl status libvirtd
sudo virsh list --all
```

### Network issues

Check network:
```bash
sudo virsh net-list --all
sudo virsh net-start default
sudo virsh net-autostart default
```

### Backup fails

Check disk space:
```bash
df -h ~/.nox/backups
```

Check S3 credentials:
```bash
aws s3 ls s3://your-bucket --endpoint-url https://your-endpoint
```

### SSH connection refused

Wait for VM to boot:
```bash
nox list  # Check if VM is running
sleep 30 && nox ssh myvm
```

## Performance

### Backup Size Comparison

| Disk Size | Used Space | Backup Size |
|-----------|------------|-------------|
| 5 GB | 500 MB | ~250 MB |
| 10 GB | 2 GB | ~1 GB |
| 20 GB | 5 GB | ~2.5 GB |

Backups are compressed and only include used disk space, not allocated space.

### Backup Speed

- **Live backup**: ~30 seconds for 5GB VM
- **S3 upload**: Depends on bandwidth
- **Restore**: ~1 minute for 5GB VM

## License

MIT
