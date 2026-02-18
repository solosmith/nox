# Testing nox (libvirt/KVM version)

## Overview
This document describes how to test the new libvirt/KVM-based nox implementation on a Raspberry Pi.

## Prerequisites

### On Raspberry Pi
1. libvirt installed and running
2. Required tools: `qemu-img`, `genisoimage`, `virt-install`
3. nox-net network configured (bridged to br0)
4. nox-pool storage pool configured

### Check Prerequisites
```bash
# Run the test script
bash /tmp/test-nox.sh
```

## Deployment

### Deploy nox to Raspberry Pi
```bash
# From your Mac
./deploy-nox.sh user@raspberry-pi-ip

# Example:
./deploy-nox.sh pi@192.168.1.100
```

## Testing Steps

### 1. Basic Functionality Test
```bash
# SSH to Raspberry Pi
ssh user@raspberry-pi-ip

# Check version
nox --version

# List VMs (should be empty initially)
nox list
```

### 2. Create Test VM
```bash
# Create a Debian VM
nox create testvm --os debian --cpus 1 --ram 512 --disk 5

# This should:
# - Create VM directory in ~/.nox/vms/testvm
# - Create qcow2 disk image
# - Generate cloud-init ISO
# - Create VM with virt-install
# - Start the VM
# - Wait for IP address
# - Display SSH credentials
```

### 3. Verify VM Status
```bash
# List VMs
nox list

# Check VM status
nox status testvm

# Verify VM is running
virsh list
```

### 4. Test SSH Access
```bash
# SSH into VM (passwordless with SSH key)
nox ssh testvm

# Inside VM, verify:
whoami  # should be 'nox'
sudo -l  # should have NOPASSWD sudo
ip a    # check network configuration
ping -c 3 8.8.8.8  # test internet connectivity
```

### 5. Test Tailscale (Original Problem)
```bash
# Inside the VM
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# This should work without permission errors
# (unlike in LXC containers)
```

### 6. Test VM Lifecycle
```bash
# Stop VM
nox stop testvm

# Start VM
nox start testvm

# Restart VM
nox restart testvm

# Delete VM
nox delete testvm
```

## Expected Results

### VM Creation
- VM should be created successfully
- VM should boot within 30-60 seconds
- VM should get IP address from local network (via br0 bridge)
- SSH credentials should be displayed

### Networking
- VM should have IP on same subnet as Raspberry Pi
- VM should be accessible from local network
- VM should have internet connectivity
- DNS should work (8.8.8.8, 8.8.4.4)

### Tailscale
- Should install without errors
- Should be able to create TUN interface
- Should connect to Tailscale network
- No "operation not permitted" errors

## Troubleshooting

### VM doesn't get IP
```bash
# Check network configuration
virsh net-list
virsh net-info nox-net

# Check bridge
ip link show br0
brctl show br0

# Check VM network interface
virsh domiflist testvm
```

### VM doesn't start
```bash
# Check VM logs
virsh console testvm

# Check libvirt logs
sudo journalctl -u libvirtd -f
```

### Can't SSH to VM
```bash
# Get VM IP manually
virsh domifaddr testvm

# Try direct SSH
ssh -o StrictHostKeyChecking=no nox@<vm-ip>
```

## Cleanup

```bash
# Delete test VM
nox delete testvm

# Remove test files
rm -rf ~/.nox/vms/testvm
```

## Success Criteria

- ✓ VM creation completes without errors
- ✓ VM boots and gets IP from local network
- ✓ SSH access works (both with nox ssh and direct)
- ✓ VM has internet connectivity
- ✓ Tailscale installs and runs without permission errors
- ✓ VM lifecycle commands work (start, stop, restart, delete)
- ✓ VM is accessible from other devices on local network
