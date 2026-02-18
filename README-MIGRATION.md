# Migration from LXC to libvirt/KVM

## Why the Change?

The original nox used LXC containers, which are lightweight but have limitations:
- **Permission issues**: Software like Tailscale requires kernel capabilities (CAP_NET_ADMIN) that LXC containers don't have by default
- **Compatibility**: Some applications expect a full VM environment with their own kernel
- **Networking**: VPNs and network tools often fail in containers

The new nox uses libvirt/KVM virtual machines, which provide:
- **Full isolation**: Each VM has its own kernel
- **Better compatibility**: VPNs, network tools, and system software work out of the box
- **Minimal overhead**: Alpine VMs use ~150-200MB RAM, Debian minimal ~200-300MB RAM

## What Changed?

### Architecture
- **Before**: LXC containers using `lxc-*` commands
- **After**: QEMU/KVM VMs using `virsh` commands via libvirt

### Storage
- **Before**: Containers in `/var/lib/lxc` and `~/.nox/containers`
- **After**: VMs in `~/.nox/vms` with qcow2 disk images

### Provisioning
- **Before**: Manual setup scripts and templates
- **After**: cloud-init for automated VM configuration

### Networking
- **Before**: LXC bridge (lxcbr0) with manual configuration
- **After**: libvirt network (nox-net) bridged to br0 for local network access

### User Interface
- **Same**: All commands remain the same (`nox create`, `nox ssh`, etc.)

## Migration Steps

### 1. Backup Existing Containers

```bash
# List existing containers
nox list

# For each container you want to keep, export data
nox ssh mycontainer
# Backup your data manually
```

### 2. Install libvirt

```bash
# Debian/Ubuntu
sudo apt-get install -y qemu-kvm libvirt-daemon-system libvirt-clients \
    virtinst bridge-utils genisoimage

# Alpine
sudo apk add qemu-system-x86_64 libvirt libvirt-daemon qemu-img \
    virt-install bridge-utils genisoimage
```

### 3. Setup libvirt Infrastructure

```bash
# Create storage pool
virsh pool-define-as nox-pool dir - - - - ~/.nox/vms
virsh pool-build nox-pool
virsh pool-start nox-pool
virsh pool-autostart nox-pool

# Create network (bridged to br0)
cat > /tmp/nox-net.xml << 'NETEOF'
<network>
  <name>nox-net</name>
  <forward mode='bridge'/>
  <bridge name='br0'/>
</network>
NETEOF

virsh net-define /tmp/nox-net.xml
virsh net-start nox-net
virsh net-autostart nox-net
```

### 4. Install New nox

```bash
# Download latest version
curl -fsSL https://raw.githubusercontent.com/solosmith/nox/main/install.sh | bash

# Or manually
sudo cp nox.py /usr/local/bin/nox
sudo chmod +x /usr/local/bin/nox
sudo cp VERSION /usr/local/bin/VERSION
```

### 5. Create New VMs

```bash
# Create VMs with same names as your old containers
nox create myvm --os debian --cpus 1 --ram 512 --disk 5

# SSH and restore your data
nox ssh myvm
```

### 6. Clean Up Old Containers (Optional)

```bash
# Stop and remove old LXC containers
sudo lxc-stop -n mycontainer
sudo lxc-destroy -n mycontainer

# Remove old nox backup
rm -f /usr/local/bin/nox-lxc.py.backup
```

## Key Differences

### Resource Usage
- **LXC**: ~50MB RAM overhead per container
- **Alpine VM**: ~150-200MB RAM total
- **Debian VM**: ~200-300MB RAM total

### Boot Time
- **LXC**: 5-10 seconds
- **VM**: 30-60 seconds (first boot with cloud-init)

### Disk Space
- **LXC**: ~200-500MB per container
- **VM**: Depends on disk size (qcow2 grows dynamically)

### Networking
- **LXC**: Isolated network, NAT to host
- **VM**: Bridged to host network, gets IP from local DHCP

## Compatibility

### What Works Better in VMs
- ✓ Tailscale and other VPNs
- ✓ Docker and container runtimes
- ✓ Kernel modules and system tools
- ✓ Network configuration tools
- ✓ Firewall and routing software

### What Was Better in LXC
- Faster boot times
- Lower memory overhead
- Simpler architecture

## Troubleshooting

### "virsh: command not found"
Install libvirt: `sudo apt-get install libvirt-clients`

### "nox-net network not found"
Run the network setup commands from step 3 above

### "nox-pool storage not found"
Run the storage pool setup commands from step 3 above

### VM doesn't get IP
Check that br0 bridge exists and is configured correctly:
```bash
ip link show br0
brctl show br0
```

### VM creation fails
Check libvirt logs:
```bash
sudo journalctl -u libvirtd -f
```

## Rollback

If you need to go back to LXC:

```bash
# Restore old version
sudo cp nox-lxc.py.backup /usr/local/bin/nox
sudo chmod +x /usr/local/bin/nox

# Your old containers should still be in /var/lib/lxc
lxc-ls -f
```

## Support

For issues or questions:
- GitHub: https://github.com/solosmith/nox/issues
- Check TESTING.md for detailed testing procedures
