#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[nox]${NC} $*"; }
warn()  { echo -e "${YELLOW}[nox]${NC} $*"; }
error() { echo -e "${RED}[nox]${NC} $*" >&2; }

detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    elif [ -f /etc/redhat-release ]; then
        echo "rhel"
    else
        echo "unknown"
    fi
}

detect_arch() {
    local arch
    arch=$(uname -m)
    case "$arch" in
        x86_64|amd64) echo "amd64" ;;
        aarch64|arm64) echo "arm64" ;;
        *) echo "$arch" ;;
    esac
}

install_debian() {
    info "Installing dependencies (Debian/Ubuntu)..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq \
        lxc \
        lxc-templates \
        bridge-utils \
        debootstrap \
        python3 \
        openssh-client

    # Enable and configure lxc networking
    sudo systemctl enable lxc-net || true
    sudo systemctl start lxc-net || true
}

install_alpine() {
    info "Installing dependencies (Alpine)..."
    sudo apk add \
        lxc \
        lxc-templates \
        lxc-download \
        bridge-utils \
        dnsmasq \
        iptables \
        python3 \
        openssh-client

    # Enable lxc service
    sudo rc-update add lxc boot || true
    sudo service lxc start || true

    # Configure LXC bridge networking for Alpine
    info "Configuring LXC bridge networking..."

    # Create bridge
    if ! ip link show lxcbr0 >/dev/null 2>&1; then
        sudo brctl addbr lxcbr0
        sudo ip addr add 10.0.3.1/24 dev lxcbr0
        sudo ip link set lxcbr0 up
    fi

    # Enable IP forwarding
    sudo sysctl -w net.ipv4.ip_forward=1
    echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf >/dev/null

    # Configure NAT
    sudo iptables -t nat -A POSTROUTING -s 10.0.3.0/24 ! -d 10.0.3.0/24 -j MASQUERADE || true

    # Configure dnsmasq for DHCP only (disable DNS to avoid conflicts)
    sudo mkdir -p /etc/dnsmasq.d

    # Create LXC DHCP config - must have .conf extension
    sudo tee /etc/dnsmasq.d/lxc.conf > /dev/null <<EOF
port=0
interface=lxcbr0
dhcp-range=10.0.3.2,10.0.3.254,12h
dhcp-option=3,10.0.3.1
dhcp-option=6,8.8.8.8
dhcp-authoritative
EOF

    # Start dnsmasq
    sudo rc-update add dnsmasq boot || true
    sudo service dnsmasq restart || true

    # Create bridge startup script
    sudo tee /etc/local.d/lxc-bridge.start > /dev/null <<'EOF'
#!/bin/sh
if ! ip link show lxcbr0 >/dev/null 2>&1; then
    brctl addbr lxcbr0
    ip addr add 10.0.3.1/24 dev lxcbr0
    ip link set lxcbr0 up
fi
sysctl -w net.ipv4.ip_forward=1
iptables -t nat -A POSTROUTING -s 10.0.3.0/24 ! -d 10.0.3.0/24 -j MASQUERADE 2>/dev/null || true
EOF
    sudo chmod +x /etc/local.d/lxc-bridge.start
    sudo rc-update add local boot || true
}

configure_lxc() {
    info "Configuring LXC..."

    # Create default LXC config if it doesn't exist
    if [ ! -f /etc/lxc/default.conf ]; then
        sudo mkdir -p /etc/lxc
        sudo tee /etc/lxc/default.conf > /dev/null <<EOF
lxc.net.0.type = veth
lxc.net.0.link = lxcbr0
lxc.net.0.flags = up
lxc.net.0.hwaddr = 00:16:3e:xx:xx:xx
EOF
    fi

    # Ensure lxc bridge is configured
    if [ ! -f /etc/default/lxc-net ]; then
        sudo mkdir -p /etc/default
        sudo tee /etc/default/lxc-net > /dev/null <<EOF
USE_LXC_BRIDGE="true"
LXC_BRIDGE="lxcbr0"
LXC_ADDR="10.0.3.1"
LXC_NETMASK="255.255.255.0"
LXC_NETWORK="10.0.3.0/24"
LXC_DHCP_RANGE="10.0.3.2,10.0.3.254"
LXC_DHCP_MAX="253"
EOF
    fi
}

enable_user_lxc() {
    info "Configuring user permissions..."
    local user
    user=$(whoami)

    # Add user to lxc-related groups if they exist
    for group in lxc lxc-dnsmasq; do
        if getent group "$group" >/dev/null 2>&1; then
            sudo usermod -aG "$group" "$user" 2>/dev/null || true
        fi
    done

    # Configure subuid/subgid for unprivileged containers
    if ! grep -q "^$user:" /etc/subuid 2>/dev/null; then
        echo "$user:100000:65536" | sudo tee -a /etc/subuid >/dev/null
    fi
    if ! grep -q "^$user:" /etc/subgid 2>/dev/null; then
        echo "$user:100000:65536" | sudo tee -a /etc/subgid >/dev/null
    fi
}

verify_install() {
    local ok=true
    info "Verifying installation..."

    for cmd in lxc-create lxc-start lxc-stop python3; do
        if command -v "$cmd" >/dev/null 2>&1; then
            info "  $cmd: $(command -v "$cmd")"
        else
            error "  $cmd: NOT FOUND"
            ok=false
        fi
    done

    if [ "$ok" = true ]; then
        info "All dependencies installed successfully."
    else
        error "Some dependencies are missing. Check the output above."
        exit 1
    fi
}

main() {
    info "nox dependency installer (LXC)"
    info "=============================="

    local distro arch
    distro=$(detect_distro)
    arch=$(detect_arch)
    info "Detected: distro=$distro arch=$arch"

    case "$distro" in
        debian|ubuntu|raspbian|linuxmint|pop)
            install_debian ;;
        alpine)
            install_alpine ;;
        *)
            error "Unsupported distro: $distro"
            error "Supported: Debian, Ubuntu, Alpine"
            error "Please install manually: lxc, lxc-templates, bridge-utils, python3"
            exit 1 ;;
    esac

    configure_lxc
    enable_user_lxc
    verify_install

    info ""
    info "Done! You may need to log out and back in for group changes to take effect."
    info "Or run: newgrp lxc"
    info ""
    info "Note: LXC commands require sudo. The nox tool will use sudo automatically."
}

main "$@"
