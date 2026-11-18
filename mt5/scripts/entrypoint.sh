#!/bin/bash

# Entrypoint script to fix permissions before the application starts
# This runs as root to ensure the container can write to mounted volumes

echo "Entrypoint: Fixing permissions for mounted directories..."

# Fix permissions for protection_config directory to ensure container can write
if [ -d "/protection_config" ]; then
    echo "Entrypoint: Setting ownership of /protection_config to abc:abc..."
    chown -R abc:abc /protection_config
    chmod -R 775 /protection_config
    echo "Entrypoint: Permissions fixed for /protection_config"
fi

# Fix permissions for config directory (includes Wine prefix)
if [ -d "/config" ]; then
    echo "Entrypoint: Setting ownership of /config to abc:abc..."
    chown -R abc:abc /config
    chmod -R 755 /config
    echo "Entrypoint: Permissions fixed for /config"
fi

# Execute the normal startup script
exec /scripts/01-start.sh
