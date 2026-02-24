#!/bin/bash
# Script to check KVM status on Raspberry Pi

echo "=== System Information ==="
uname -a
echo ""

echo "=== CPU Architecture ==="
lscpu | grep -E "Architecture|Vendor|Model name|Virtualization"
echo ""

echo "=== KVM Module Status ==="
lsmod | grep kvm || echo "KVM module not loaded"
echo ""

echo "=== KVM Device ==="
ls -l /dev/kvm 2>/dev/null || echo "/dev/kvm not found"
echo ""

echo "=== Libvirt Version ==="
virsh --version 2>/dev/null || echo "virsh not installed"
echo ""

echo "=== QEMU Version ==="
qemu-system-aarch64 --version 2>/dev/null || qemu-system-arm --version 2>/dev/null || echo "QEMU not installed"
echo ""

echo "=== Running VMs ==="
virsh --connect qemu:///system list --all 2>/dev/null || echo "Cannot connect to libvirt"
echo ""

echo "=== Check if VMs use KVM ==="
for vm in $(virsh --connect qemu:///system list --name --all 2>/dev/null); do
    if [ -n "$vm" ]; then
        echo "VM: $vm"
        virsh --connect qemu:///system dumpxml "$vm" 2>/dev/null | grep -E "<domain type=|<type>|cpu mode=" | head -5
        echo ""
    fi
done
