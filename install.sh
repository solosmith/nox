#!/usr/bin/env bash
# nox installer - Complete installation script for KVM/libvirt
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
    error "macOS is not supported. Please use a Linux system with KVM support."
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

info "nox - Lightweight VM Manager using KVM/libvirt"
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
                info "Will update nox and verify dependencies"
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
    # Already up to date - ask if user wants to verify dependencies
    read -p "Verify and update dependencies if needed? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        SKIP_DEPS=true
    fi
else
    # Update available - install script always checks dependencies
    info "Will update nox and verify dependencies"
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

check_kvm_support() {
    info "Checking KVM support..."
    
    local arch=$(detect_arch)
    
    if [ "$arch" = "amd64" ]; then
        # Check for Intel VT-x or AMD-V
        if grep -qE 'vmx|svm' /proc/cpuinfo; then
            info "✓ CPU supports hardware virtualization (VT-x/AMD-V)"
            return 0
        else
            warn "⚠ CPU does not support hardware virtualization"
            warn "VMs will run in emulation mode (slow)"
            return 1
        fi
    elif [ "$arch" = "arm64" ]; then
        # ARM64 virtualization check
        if [ -c /dev/kvm ]; then
            info "✓ KVM device found (/dev/kvm)"
            return 0
        else
            warn "⚠ /dev/kvm not found - checking kernel support..."
            if dmesg | grep -qi "kvm.*hyp mode initialized"; then
                info "✓ KVM initialized in kernel"
                return 0
            else
                warn "⚠ KVM may not be available on this ARM64 system"
                return 1
            fi
        fi
    fi
    
    return 1
}

enable_kvm() {
    info "Enabling KVM..."
    
    local arch=$(detect_arch)
    
    # Load KVM modules
    if [ "$arch" = "amd64" ]; then
        # Try Intel first, then AMD
        if grep -q "vmx" /proc/cpuinfo; then
            $SUDO modprobe kvm_intel 2>/dev/null || $SUDO modprobe kvm 2>/dev/null || true
        elif grep -q "svm" /proc/cpuinfo; then
            $SUDO modprobe kvm_amd 2>/dev/null || $SUDO modprobe kvm 2>/dev/null || true
        fi
    elif [ "$arch" = "arm64" ]; then
        # ARM64 KVM is usually built-in, but try loading if module exists
        $SUDO modprobe kvm 2>/dev/null || true
    fi
    
    # Verify KVM device exists
    if [ -c /dev/kvm ]; then
        info "✓ KVM device available: /dev/kvm"
        
        # Set proper permissions
        if [ -n "$SUDO" ]; then
            local user=$(whoami)
            $SUDO chown root:kvm /dev/kvm 2>/dev/null || true
            $SUDO chmod 660 /dev/kvm 2>/dev/null || true
        fi
    else
        warn "⚠ /dev/kvm not available - VMs will use emulation"
    fi
}

install_debian() {
    info "Installing/updating dependencies (Debian/Ubuntu)..."
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq \
        qemu-system \
        qemu-utils \
        libvirt-daemon-system \
        libvirt-clients \
        virtinst \
        bridge-utils \
        genisoimage \
        python3 \
        openssh-client \
        dnsmasq-base
    
    # Enable and start libvirtd
    $SUDO systemctl enable libvirtd
    $SUDO systemctl start libvirtd
    
    # Enable KVM
    enable_kvm
    
    # Configure default network
    configure_libvirt_network
}

install_alpine() {
    info "Installing/updating dependencies (Alpine)..."
    $SUDO apk add \
        qemu-system-x86_64 \
        qemu-system-aarch64 \
        qemu-img \
        libvirt-daemon \
        libvirt-client \
        virt-install \
        bridge-utils \
        cdrkit \
        python3 \
        openssh-client \
        dnsmasq
    
    # Enable and start libvirtd
    $SUDO rc-update add libvirtd boot || true
    $SUDO service libvirtd start || true
    
    # Enable KVM
    enable_kvm
    
    # Configure default network
    configure_libvirt_network
}

configure_libvirt_network() {
    info "Configuring libvirt networks..."
    
    # Start default network if it exists
    if virsh --connect qemu:///system net-list --all 2>/dev/null | grep -q "default"; then
        virsh --connect qemu:///system net-start default 2>/dev/null || true
        virsh --connect qemu:///system net-autostart default 2>/dev/null || true
        info "✓ Default network configured"
    else
        warn "⚠ Default network not found - will be created on first VM"
    fi
    
    # Create nox-net network if it doesn't exist
    if ! virsh --connect qemu:///system net-list --all 2>/dev/null | grep -q "nox-net"; then
        info "Creating nox-net network..."
        
        # Find available bridge number
        local bridge_num=1
        while ip link show virbr${bridge_num} >/dev/null 2>&1; do
            bridge_num=$((bridge_num + 1))
        done
        
        # Find available subnet
        local subnet_third=100
        while ip route | grep -q "192.168.${subnet_third}."; do
            subnet_third=$((subnet_third + 1))
        done
        
        virsh --connect qemu:///system net-define /dev/stdin <<EOF
<network>
  <name>nox-net</name>
  <forward mode='nat'/>
  <bridge name='virbr${bridge_num}' stp='on' delay='0'/>
  <ip address='192.168.${subnet_third}.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='192.168.${subnet_third}.2' end='192.168.${subnet_third}.254'/>
    </dhcp>
  </ip>
</network>
EOF
        
        virsh --connect qemu:///system net-start nox-net 2>/dev/null || true
        virsh --connect qemu:///system net-autostart nox-net 2>/dev/null || true
        info "✓ nox-net network created (192.168.${subnet_third}.0/24)"
    else
        info "✓ nox-net network already exists"
    fi
}

enable_user_permissions() {
    info "Configuring user permissions..."
    local user
    user=$(whoami)
    
    # Add user to libvirt and kvm groups
    for group in libvirt libvirt-qemu kvm; do
        if getent group "$group" >/dev/null 2>&1; then
            $SUDO usermod -aG "$group" "$user" 2>/dev/null || true
            info "✓ Added $user to $group group"
        fi
    done
    
    # Configure polkit for libvirt access without password
    if [ -d /etc/polkit-1/rules.d ]; then
        $SUDO tee /etc/polkit-1/rules.d/50-libvirt.rules > /dev/null <<EOF
polkit.addRule(function(action, subject) {
    if (action.id == "org.libvirt.unix.manage" &&
        subject.isInGroup("libvirt")) {
            return polkit.Result.YES;
    }
});
EOF
        info "✓ Configured polkit for libvirt access"
    fi
}

verify_install() {
    local ok=true
    info "Verifying installation..."
    
    for cmd in virsh qemu-img virt-install python3; do
        if command -v "$cmd" >/dev/null 2>&1; then
            info "  ✓ $cmd: $(command -v "$cmd")"
        else
            error "  ✗ $cmd: NOT FOUND"
            ok=false
        fi
    done
    
    # Check libvirtd status
    if systemctl is-active --quiet libvirtd 2>/dev/null || service libvirtd status >/dev/null 2>&1; then
        info "  ✓ libvirtd: running"
    else
        warn "  ⚠ libvirtd: not running"
    fi
    
    # Check KVM
    if [ -c /dev/kvm ]; then
        info "  ✓ KVM: available"
    else
        warn "  ⚠ KVM: not available (will use emulation)"
    fi
    
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
    
    # Check KVM support
    check_kvm_support || warn "Continuing without KVM acceleration"
    
    if [ "$SKIP_DEPS" = false ]; then
        case "$distro" in
            debian|ubuntu|raspbian|linuxmint|pop)
                install_debian ;;
            alpine)
                install_alpine ;;
            *)
                error "Unsupported distro: $distro"
                error "Supported: Debian, Ubuntu, Alpine"
                error "Please install manually: qemu, libvirt, virt-install, python3"
                exit 1 ;;
        esac
        
        enable_user_permissions
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
    
    # Show post-install instructions
    if groups | grep -qE "libvirt|kvm"; then
        info "Quick start:"
    else
        warn "IMPORTANT: You need to log out and log back in for group changes to take effect!"
        info ""
        info "After logging back in, quick start:"
    fi
    
    info "  nox --version"
    info "  nox create myvm --os debian --cpus 2 --ram 1024 --disk 10"
    info "  nox list"
    info "  nox ssh myvm"
    info ""
    info "Update nox: nox update"
    info "For more: https://github.com/solosmith/nox"
}

main "$@"
