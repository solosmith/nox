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
        docker.io \
        python3 \
        openssh-client
    sudo systemctl enable docker
    sudo systemctl start docker
}

install_fedora() {
    info "Installing dependencies (Fedora/RHEL/CentOS)..."
    sudo dnf install -y \
        docker \
        python3 \
        openssh-clients
    sudo systemctl enable docker
    sudo systemctl start docker
}

install_arch() {
    info "Installing dependencies (Arch)..."
    sudo pacman -Sy --noconfirm \
        docker \
        python \
        openssh
    sudo systemctl enable docker
    sudo systemctl start docker
}

install_alpine() {
    info "Installing dependencies (Alpine)..."
    sudo apk add \
        docker \
        python3 \
        openssh-client
    sudo rc-update add docker boot
    sudo service docker start
}

install_suse() {
    info "Installing dependencies (openSUSE/SLES)..."
    sudo zypper install -y \
        docker \
        python3 \
        openssh
    sudo systemctl enable docker
    sudo systemctl start docker
}

enable_docker() {
    info "Configuring Docker..."
    local user
    user=$(whoami)
    if getent group docker >/dev/null 2>&1; then
        sudo usermod -aG docker "$user" 2>/dev/null || true
        info "Added $user to docker group"
    fi
}

verify_install() {
    local ok=true
    for cmd in docker python3; do
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
    info "nox dependency installer"
    info "========================"

    local distro arch
    distro=$(detect_distro)
    arch=$(detect_arch)
    info "Detected: distro=$distro arch=$arch"

    case "$distro" in
        debian|ubuntu|raspbian|linuxmint|pop)
            install_debian ;;
        fedora|rhel|centos|rocky|alma)
            install_fedora ;;
        arch|manjaro|endeavouros)
            install_arch ;;
        alpine)
            install_alpine ;;
        opensuse*|sles)
            install_suse ;;
        *)
            error "Unsupported distro: $distro"
            error "Please install manually: docker, python3"
            exit 1 ;;
    esac

    enable_docker
    verify_install

    info ""
    info "Done! You may need to log out and back in for group changes to take effect."
    info "Or run: newgrp docker"
}

main "$@"
