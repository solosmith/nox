#!/usr/bin/env bash
# nox installer - One-line installation script
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

info "Installing nox - LXC Container Manager"
info "========================================"

# Download and run install.sh
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

info "Downloading nox from GitHub..."
if command -v curl >/dev/null 2>&1; then
    curl -fsSL https://raw.githubusercontent.com/solosmith/nox/main/install.sh -o install.sh
    curl -fsSL https://raw.githubusercontent.com/solosmith/nox/main/nox.py -o nox.py
elif command -v wget >/dev/null 2>&1; then
    wget -q https://raw.githubusercontent.com/solosmith/nox/main/install.sh -O install.sh
    wget -q https://raw.githubusercontent.com/solosmith/nox/main/nox.py -O nox.py
else
    error "Neither curl nor wget found. Please install one of them."
    exit 1
fi

info "Installing dependencies..."
$SUDO bash install.sh

info "Installing nox command..."
$SUDO cp nox.py /usr/local/bin/nox
$SUDO chmod +x /usr/local/bin/nox

# Setup SSH key if not exists
if [ ! -f ~/.ssh/id_ed25519 ]; then
    info "Generating SSH key for passwordless access..."
    ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N '' -q
fi

# Cleanup
cd /
rm -rf "$TEMP_DIR"

info ""
info "✓ nox installed successfully!"
info ""
info "Quick start:"
info "  nox create mycontainer --os debian"
info "  nox list"
info "  nox ssh mycontainer"
info ""
info "For more information, visit: https://github.com/solosmith/nox"
