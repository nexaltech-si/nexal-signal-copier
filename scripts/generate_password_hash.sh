#!/bin/bash

# Script to generate Traefik basic auth password hash
# Usage: ./generate_password_hash.sh

echo "==================================="
echo "Traefik Password Hash Generator"
echo "==================================="
echo ""

# Check if htpasswd is installed
if ! command -v htpasswd &> /dev/null; then
    echo "❌ htpasswd is not installed."
    echo ""
    echo "Install it with:"
    echo "  macOS:   brew install httpd"
    echo "  Ubuntu:  sudo apt-get install apache2-utils"
    echo "  CentOS:  sudo yum install httpd-tools"
    exit 1
fi

# Prompt for username
read -p "Enter username [admin]: " USERNAME
USERNAME=${USERNAME:-admin}

# Prompt for password
echo ""
echo "Enter password (will be hidden):"
read -s PASSWORD

if [ -z "$PASSWORD" ]; then
    echo "❌ Password cannot be empty"
    exit 1
fi

echo ""
echo "Generating hash..."
echo ""

# Generate the hash
HASH=$(htpasswd -nbB "$USERNAME" "$PASSWORD" | sed -e s/\\$/\\$\\$/g)

echo "==================================="
echo "✅ Generated Hash:"
echo "==================================="
echo "$HASH"
echo ""
echo "==================================="
echo "Add this to docker-compose.yml:"
echo "==================================="
echo "- \"traefik.http.middlewares.dashboard-auth.basicauth.users=$HASH\""
echo ""
echo "Then run: docker-compose up -d --force-recreate dashboard"
echo ""
