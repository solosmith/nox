#!/bin/bash
set -euo pipefail

echo "Installing Claude Code..."

# Detect OS and architecture
if [ -f /etc/debian_version ]; then
    OS="debian"
elif [ -f /etc/alpine-release ]; then
    OS="alpine"
else
    echo "Unsupported OS"
    exit 1
fi

ARCH=$(uname -m)
case "$ARCH" in
    x86_64|amd64)
        ARCH="x64"
        ;;
    aarch64|arm64)
        ARCH="arm64"
        ;;
    *)
        echo "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

case "$OS" in
    debian)
        # Install dependencies
        apt-get update
        apt-get install -y curl ca-certificates

        # Download and install Claude Code
        CLAUDE_URL="https://storage.googleapis.com/osprey-downloads-c02f6a0d-347c-492b-a752-3e0651722e97/nest-cli/latest/linux-${ARCH}/claude-code"
        curl -fsSL "$CLAUDE_URL" -o /usr/local/bin/claude-code
        chmod +x /usr/local/bin/claude-code
        ;;

    alpine)
        # Install dependencies
        apk add --no-cache curl ca-certificates

        # Download and install Claude Code
        CLAUDE_URL="https://storage.googleapis.com/osprey-downloads-c02f6a0d-347c-492b-a752-3e0651722e97/nest-cli/latest/linux-${ARCH}/claude-code"
        curl -fsSL "$CLAUDE_URL" -o /usr/local/bin/claude-code
        chmod +x /usr/local/bin/claude-code
        ;;
esac

echo "Claude Code installed successfully"
echo ""
echo "To get started, run:"
echo "  claude-code --help"
echo ""
echo "To authenticate:"
echo "  claude-code auth login"
