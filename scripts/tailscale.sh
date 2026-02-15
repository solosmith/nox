#!/bin/bash
set -euo pipefail

echo "Installing Tailscale..."

# Detect OS
if [ -f /etc/debian_version ]; then
    OS="debian"
elif [ -f /etc/alpine-release ]; then
    OS="alpine"
else
    echo "Unsupported OS"
    exit 1
fi

case "$OS" in
    debian)
        # Install Tailscale
        curl -fsSL https://tailscale.com/install.sh | sh
        ;;

    alpine)
        # Install Tailscale
        apk add --no-cache tailscale

        # Enable and start tailscaled
        rc-update add tailscale boot
        service tailscale start
        ;;
esac

echo "Tailscale installed successfully"
echo ""
echo "To connect to your tailnet, run:"
echo "  sudo tailscale up"
echo ""
echo "Or with an auth key:"
echo "  sudo tailscale up --authkey=tskey-auth-xxxxx"
