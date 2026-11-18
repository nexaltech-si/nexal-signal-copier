#!/bin/bash
set +e

echo "🚀 Starting Trading Bot..."
echo "=========================="

# Generate Prisma client (in case schema changed)
echo "🔧 Generating Prisma client..."
prisma generate --schema=/app/prisma/schema.prisma

# Create the database on first start, apply pending migrations afterwards
if ! sh /app/scripts/init_database.sh; then
    echo "⚠️  Database setup failed."
    if [ "$ALLOW_DB_RESET" = "true" ]; then
        echo "   ALLOW_DB_RESET=true — resetting the database (ALL DATA IS LOST)..."
        prisma migrate reset --force --schema=/app/prisma/schema.prisma
    else
        echo "   Continuing with the database as it is. Fix the error above, or set"
        echo "   ALLOW_DB_RESET=true to wipe and recreate it (development only)."
    fi
fi

# Start the trading bot
echo "🤖 Starting main application..."
exec python main.py
