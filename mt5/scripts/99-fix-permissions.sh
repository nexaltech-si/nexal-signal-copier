#!/bin/bash

# Permission fix script for linuxserver base image cont-init.d
# Runs as root before switching to abc user

echo "cont-init: Fixing permissions for mounted directories..."

# Fix permissions for protection_config directory
if [ -d "/protection_config" ]; then
    echo "cont-init: Setting ownership of /protection_config to abc:abc..."
    chown -R abc:abc /protection_config
    chmod -R 775 /protection_config
    echo "cont-init: Permissions fixed for /protection_config"
fi

# Fix permissions for config directory (includes Wine prefix)
if [ -d "/config" ]; then
    echo "cont-init: Setting ownership of /config to abc:abc..."
    chown -R abc:abc /config
    chmod -R 755 /config
    echo "cont-init: Permissions fixed for /config"
fi
