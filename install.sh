#!/usr/bin/env bash
# nox installer - Complete installation script
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[nox]${NC} $*"; }
warn()  { echo -e "${YELLOW}[nox]${NC} $*"; }
error() { echo -e "${RED}[nox]${NC} $*" >&2; }

# Check if running on macOS
if [[ "$OSTYPE" == "darwin"* ]]; then
    error "macOS is not supported. Please use a Linux system (Debian, Ubuntu, or Alpine)."
    exit 1
fi

# Detect if running as root
if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
else
    SUDO=""
fi

# GitHub repository URL
GITHUB_RAW_URL="https://raw.githubusercontent.com/solosmith/nox/main"

info "nox - LXC Container Manager"
info "========================================"

# Check if nox is already installed
check_existing_installation() {
    if command -v nox >/dev/null 2>&1; then
        CURRENT_VERSION="unknown"
        if [ -f /usr/local/bin/VERSION ]; then
            CURRENT_VERSION=$(cat /usr/local/bin/VERSION)
        fi
        info "Found existing nox installation (version: $CURRENT_VERSION)"

        # Check for latest version
        info "Checking for updates..."
        TEMP_DIR=$(mktemp -d)
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL "$GITHUB_RAW_URL/VERSION" -o "$TEMP_DIR/VERSION" 2>/dev/null || true
        elif command -v wget >/dev/null 2>&1; then
            wget -q "$GITHUB_RAW_URL/VERSION" -O "$TEMP_DIR/VERSION" 2>/dev/null || true
        fi

        if [ -f "$TEMP_DIR/VERSION" ]; then
            LATEST_VERSION=$(cat "$TEMP_DIR/VERSION")
            if [ "$CURRENT_VERSION" = "$LATEST_VERSION" ]; then
                info "Already up to date (version $CURRENT_VERSION)"
                rm -rf "$TEMP_DIR"

                # Still verify dependencies
                info "Verifying dependencies..."
                return 0
            else
                info "Update available: $CURRENT_VERSION → $LATEST_VERSION"
                rm -rf "$TEMP_DIR"
                return 1
            fi
        fi
        rm -rf "$TEMP_DIR"
        return 1
    fi
    return 1
}

SKIP_DEPS=false
if check_existing_installation; then
    # Ask if user wants to verify/reinstall dependencies
    read -p "Verify and reinstall dependencies if needed? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        SKIP_DEPS=true
    fi
fi

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

is_virtualized() {
    # Check if running in a VM or container
    if [ -f /proc/cpuinfo ]; then
        if grep -qi "hypervisor" /proc/cpuinfo; then
            return 0
        fi
    fi
    if systemd-detect-virt >/dev/null 2>&1; then
        local virt=$(systemd-detect-virt)
        if [ "$virt" != "none" ]; then
            return 0
        fi
    fi
    return 1
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

    # Check if running in virtualized environment
    if is_virtualized; then
        warn "Detected virtualized environment - using isolated networking"
        warn "For local network access, install on physical hardware"

        # Use isolated bridge with NAT
        if ! ip link show lxcbr0 >/dev/null 2>&1; then
            info "Creating isolated bridge lxcbr0..."
            sudo brctl addbr lxcbr0
            sudo ip addr add 10.0.3.1/24 dev lxcbr0
            sudo ip link set lxcbr0 up

            # Setup NAT for internet access
            PRIMARY_IF=$(ip route | grep default | awk '{print $5}' | head -n1)
            sudo iptables -t nat -A POSTROUTING -s 10.0.3.0/24 -o "$PRIMARY_IF" -j MASQUERADE
            sudo iptables -A FORWARD -i lxcbr0 -o "$PRIMARY_IF" -j ACCEPT
            sudo iptables -A FORWARD -i "$PRIMARY_IF" -o lxcbr0 -m state --state RELATED,ESTABLISHED -j ACCEPT
        fi
    else
        # Detect primary network interface
        PRIMARY_IF=$(ip route | grep default | awk '{print $5}' | head -n1)
        info "Detected primary interface: $PRIMARY_IF"

        # Create bridge on physical interface for local network access
        if ! ip link show lxcbr0 >/dev/null 2>&1; then
            info "Creating bridge lxcbr0 on $PRIMARY_IF..."
            sudo brctl addbr lxcbr0
            sudo brctl addif lxcbr0 "$PRIMARY_IF"

            # Get current IP config from primary interface
            PRIMARY_IP=$(ip -4 addr show "$PRIMARY_IF" | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
            PRIMARY_MASK=$(ip -4 addr show "$PRIMARY_IF" | grep -oP '(?<=inet\s)\d+(\.\d+){3}/\d+' | cut -d'/' -f2)
            PRIMARY_GW=$(ip route | grep default | awk '{print $3}' | head -n1)

            # Move IP from interface to bridge
            if [ -n "$PRIMARY_IP" ]; then
                sudo ip addr del "$PRIMARY_IP/$PRIMARY_MASK" dev "$PRIMARY_IF" || true
                sudo ip addr add "$PRIMARY_IP/$PRIMARY_MASK" dev lxcbr0
            fi

            sudo ip link set lxcbr0 up
            sudo ip link set "$PRIMARY_IF" up

            # Restore default route
            if [ -n "$PRIMARY_GW" ]; then
                sudo ip route add default via "$PRIMARY_GW" dev lxcbr0 || true
            fi
        fi
    fi

    # Enable IP forwarding
    sudo sysctl -w net.ipv4.ip_forward=1
    echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf >/dev/null

    # Update LXC default config to use bridge
    sudo tee /etc/lxc/default.conf > /dev/null <<EOF
lxc.net.0.type = veth
lxc.net.0.link = lxcbr0
lxc.net.0.flags = up
lxc.net.0.hwaddr = 00:16:3e:xx:xx:xx
EOF

    # Disable lxc-net service (we're using our own bridge)
    sudo systemctl disable lxc-net || true
    sudo systemctl stop lxc-net || true
}

install_alpine() {
    info "Installing dependencies (Alpine)..."
    sudo apk add \
        lxc \
        lxc-templates \
        lxc-download \
        bridge-utils \
        iptables \
        python3 \
        openssh-client

    # Enable lxc service
    sudo rc-update add lxc boot || true
    sudo service lxc start || true

    # Check if running in virtualized environment
    if is_virtualized; then
        warn "Detected virtualized environment - using isolated networking"
        warn "For local network access, install on physical hardware"

        # Use isolated bridge with NAT
        if ! ip link show lxcbr0 >/dev/null 2>&1; then
            info "Creating isolated bridge lxcbr0..."
            sudo brctl addbr lxcbr0
            sudo ip addr add 10.0.3.1/24 dev lxcbr0
            sudo ip link set lxcbr0 up

            # Setup NAT for internet access
            PRIMARY_IF=$(ip route | grep default | awk '{print $5}' | head -n1)
            sudo iptables -t nat -A POSTROUTING -s 10.0.3.0/24 -o "$PRIMARY_IF" -j MASQUERADE
            sudo iptables -A FORWARD -i lxcbr0 -o "$PRIMARY_IF" -j ACCEPT
            sudo iptables -A FORWARD -i "$PRIMARY_IF" -o lxcbr0 -m state --state RELATED,ESTABLISHED -j ACCEPT
        fi
    else
        # Detect primary network interface
        PRIMARY_IF=$(ip route | grep default | awk '{print $5}' | head -n1)
        info "Detected primary interface: $PRIMARY_IF"

        # Configure LXC bridge networking for Alpine
        info "Configuring LXC bridge networking..."

        # Create bridge on physical interface
        if ! ip link show lxcbr0 >/dev/null 2>&1; then
            info "Creating bridge lxcbr0 on $PRIMARY_IF..."
            sudo brctl addbr lxcbr0
            sudo brctl addif lxcbr0 "$PRIMARY_IF"

            # Get current IP config from primary interface
            PRIMARY_IP=$(ip -4 addr show "$PRIMARY_IF" | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
            PRIMARY_MASK=$(ip -4 addr show "$PRIMARY_IF" | grep -oP '(?<=inet\s)\d+(\.\d+){3}/\d+' | cut -d'/' -f2)
            PRIMARY_GW=$(ip route | grep default | awk '{print $3}' | head -n1)

            # Move IP from interface to bridge
            if [ -n "$PRIMARY_IP" ]; then
                sudo ip addr del "$PRIMARY_IP/$PRIMARY_MASK" dev "$PRIMARY_IF" || true
                sudo ip addr add "$PRIMARY_IP/$PRIMARY_MASK" dev lxcbr0
            fi

            sudo ip link set lxcbr0 up
            sudo ip link set "$PRIMARY_IF" up

            # Restore default route
            if [ -n "$PRIMARY_GW" ]; then
                sudo ip route add default via "$PRIMARY_GW" dev lxcbr0 || true
            fi
        fi
    fi

    # Enable IP forwarding
    sudo sysctl -w net.ipv4.ip_forward=1
    echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf >/dev/null

    # Create bridge startup script for Alpine
    if ! is_virtualized; then
        sudo tee /etc/local.d/lxc-bridge.start > /dev/null <<'EOF'
#!/bin/sh
PRIMARY_IF=$(ip route | grep default | awk '{print $5}' | head -n1)
if ! ip link show lxcbr0 >/dev/null 2>&1; then
    brctl addbr lxcbr0
    brctl addif lxcbr0 "$PRIMARY_IF"
    PRIMARY_IP=$(ip -4 addr show "$PRIMARY_IF" | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
    PRIMARY_MASK=$(ip -4 addr show "$PRIMARY_IF" | grep -oP '(?<=inet\s)\d+(\.\d+){3}/\d+' | cut -d'/' -f2)
    if [ -n "$PRIMARY_IP" ]; then
        ip addr del "$PRIMARY_IP/$PRIMARY_MASK" dev "$PRIMARY_IF" 2>/dev/null || true
        ip addr add "$PRIMARY_IP/$PRIMARY_MASK" dev lxcbr0
    fi
    ip link set lxcbr0 up
    ip link set "$PRIMARY_IF" up
    PRIMARY_GW=$(ip route | grep default | awk '{print $3}' | head -n1)
    if [ -n "$PRIMARY_GW" ]; then
        ip route add default via "$PRIMARY_GW" dev lxcbr0 2>/dev/null || true
    fi
fi
sysctl -w net.ipv4.ip_forward=1
EOF
        sudo chmod +x /etc/local.d/lxc-bridge.start
        sudo rc-update add local boot || true
    fi
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
    local distro arch
    distro=$(detect_distro)
    arch=$(detect_arch)
    info "Detected: distro=$distro arch=$arch"

    if [ "$SKIP_DEPS" = false ]; then
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
    else
        info "Skipping dependency installation"
    fi

    # Download and install nox.py
    info ""
    info "Installing nox command..."

    TEMP_DIR=$(mktemp -d)
    cd "$TEMP_DIR"

    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$GITHUB_RAW_URL/nox.py" -o nox.py || {
            error "Failed to download nox.py from GitHub"
            error "Make sure the repository is public or accessible"
            cd /
            rm -rf "$TEMP_DIR"
            exit 1
        }
        curl -fsSL "$GITHUB_RAW_URL/VERSION" -o VERSION || {
            error "Failed to download VERSION from GitHub"
            cd /
            rm -rf "$TEMP_DIR"
            exit 1
        }
    elif command -v wget >/dev/null 2>&1; then
        wget -q "$GITHUB_RAW_URL/nox.py" -O nox.py || {
            error "Failed to download nox.py from GitHub"
            error "Make sure the repository is public or accessible"
            cd /
            rm -rf "$TEMP_DIR"
            exit 1
        }
        wget -q "$GITHUB_RAW_URL/VERSION" -O VERSION || {
            error "Failed to download VERSION from GitHub"
            cd /
            rm -rf "$TEMP_DIR"
            exit 1
        }
    else
        warn "Neither curl nor wget found. Please download nox.py manually."
        warn "Visit: https://github.com/solosmith/nox"
        cd /
        rm -rf "$TEMP_DIR"
        exit 0
    fi

    # Get version from downloaded file
    INSTALL_VERSION=$(cat VERSION)

    $SUDO cp nox.py /usr/local/bin/nox
    $SUDO chmod +x /usr/local/bin/nox
    $SUDO cp VERSION /usr/local/bin/VERSION

    cd /
    rm -rf "$TEMP_DIR"

    # Setup SSH key if not exists
    if [ ! -f ~/.ssh/id_ed25519 ]; then
        info "Generating SSH key for passwordless access..."
        ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N '' -q
    fi

    info ""
    info "✓ nox installed successfully! (version $INSTALL_VERSION)"
    info ""
    info "Quick start:"
    info "  nox --version"
    info "  nox create mycontainer --os debian"
    info "  nox list"
    info "  nox ssh mycontainer"
    info ""
    info "Update nox: nox update"
    info "For more: https://github.com/solosmith/nox"
}

main "$@"
