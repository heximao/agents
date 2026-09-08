#!/bin/bash
# md2wechat skill wrapper script
# This script wraps the md2wechat CLI for use as an OpenCode skill

# Ensure PATH includes user local bin
export PATH="$HOME/.local/bin:$PATH"

# Check if md2wechat is installed
if ! command -v md2wechat &> /dev/null; then
    echo "md2wechat not found. Installing..."
    mkdir -p ~/.local/bin
    
    # Detect OS and architecture
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)
    
    case "$ARCH" in
        x86_64|amd64)
            ARCH="amd64"
            ;;
        arm64|aarch64)
            ARCH="arm64"
            ;;
        *)
            echo "Unsupported architecture: $ARCH"
            exit 1
            ;;
    esac
    
    BINARY="md2wechat-${OS}-${ARCH}"
    
    echo "Downloading md2wechat for ${OS}/${ARCH}..."
    curl -Lo ~/.local/bin/md2wechat "https://github.com/geekjourneyx/md2wechat-skill/releases/latest/download/${BINARY}"
    chmod +x ~/.local/bin/md2wechat
    
    if ! command -v md2wechat &> /dev/null; then
        echo "Failed to install md2wechat"
        exit 1
    fi
    
    echo "md2wechat installed successfully!"
fi

# Run md2wechat with all arguments
md2wechat "$@"
