#!/bin/bash
# Sync schema from primary (bot) to dashboard
# The primary schema is prisma/schema.prisma (repository root)

set -e

PRIMARY_SCHEMA="prisma/schema.prisma"
DASHBOARD_SCHEMA="dashboard/prisma/schema.prisma"

echo "🔄 Syncing Prisma Schemas"
echo "========================="
echo ""
echo "📍 Primary schema: $PRIMARY_SCHEMA"
echo "📍 Dashboard schema: $DASHBOARD_SCHEMA"
echo ""

# Check if primary schema exists
if [ ! -f "$PRIMARY_SCHEMA" ]; then
    echo "❌ Primary schema not found at $PRIMARY_SCHEMA"
    exit 1
fi

# Backup dashboard schema
if [ -f "$DASHBOARD_SCHEMA" ]; then
    echo "💾 Backing up dashboard schema..."
    cp "$DASHBOARD_SCHEMA" "$DASHBOARD_SCHEMA.backup"
    echo "   Backup saved to: $DASHBOARD_SCHEMA.backup"
fi

# Copy primary schema to dashboard
echo "📋 Copying primary schema to dashboard..."
cp "$PRIMARY_SCHEMA" "$DASHBOARD_SCHEMA"

# Update the generator for JavaScript
echo "🔧 Updating generator for JavaScript client..."
sed -i '1,10s|// Prisma Schema for Telegram Trading Bot|// Prisma Schema for Next.js Dashboard|' "$DASHBOARD_SCHEMA"
sed -i '1,10s|// Clean database structure with proper relationships|// Uses the same database as the Python bot|' "$DASHBOARD_SCHEMA"
sed -i 's|provider.*=.*"prisma-client-py"|  provider      = "prisma-client-js"|' "$DASHBOARD_SCHEMA"
sed -i '/interface.*=.*"asyncio"/d' "$DASHBOARD_SCHEMA"
sed -i '/recursive_type_depth.*=.*5/d' "$DASHBOARD_SCHEMA"
sed -i '/provider.*=.*"prisma-client-js"/a\  binaryTargets = ["native", "linux-musl-openssl-3.0.x"]' "$DASHBOARD_SCHEMA"

echo ""
echo "✅ Schema sync complete!"
echo ""
echo "📊 Differences (should only be generator config):"
diff -u "$PRIMARY_SCHEMA" "$DASHBOARD_SCHEMA" | head -20 || true

echo ""
echo "Next steps:"
echo "1. Review the changes above"
echo "2. Commit both schema files if changes look good"
echo "3. Rebuild containers: docker compose build"
echo "4. Restart: docker compose up -d"
