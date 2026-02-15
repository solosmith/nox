#!/bin/bash
set -euo pipefail

echo "Installing Docker..."

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
        # Install dependencies
        apt-get update
        apt-get install -y ca-certificates curl gnupg

        # Add Docker's official GPG key
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg

        # Add Docker repository
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
          $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
          tee /etc/apt/sources.list.d/docker.list > /dev/null

        # Install Docker
        apt-get update
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

        # Add nox user to docker group
        usermod -aG docker nox
        ;;

    alpine)
        # Install Docker
        apk add --no-cache docker docker-compose

        # Enable and start Docker
        rc-update add docker boot
        service docker start

        # Add nox user to docker group
        addgroup nox docker
        ;;
esac

echo "Docker installed successfully"
echo "Run 'docker --version' to verify"
