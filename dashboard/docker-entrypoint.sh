#!/bin/sh
# Don't exit on error for migration handling
set +e

echo "🎨 Starting Dashboard..."
echo "======================"

# Wait for database to be created by trading bot
echo "⏳ Waiting for database..."
max_attempts=30
attempt=0
while [ ! -f /app/data/trading_bot.db ] && [ $attempt -lt $max_attempts ]; do
    echo "   Attempt $((attempt + 1))/$max_attempts - waiting for database file..."
    sleep 2
    attempt=$((attempt + 1))
done

if [ -f /app/data/trading_bot.db ]; then
    echo "✅ Database file found"
    
    # Generate Prisma client (in case schema changed)
    echo "🔧 Generating Prisma client..."
    node /app/node_modules/.bin/prisma generate --schema=/app/prisma/schema.prisma
    
    # Run dashboard Prisma migrations only if migration files are available
    if [ -d "/app/prisma/migrations" ] && find "/app/prisma/migrations" -name "migration.sql" -mindepth 2 2>/dev/null | grep -q .; then
        echo "📊 Running dashboard database migrations..."
        node /app/node_modules/.bin/prisma migrate deploy --schema=/app/prisma/schema.prisma
        
        if [ $? -eq 0 ]; then
            echo "✅ Dashboard migrations completed successfully"
        else
            echo "⚠️  Migration failed, attempting to resolve..."
            
            # Find the latest migration folder name dynamically
            latest_migration=$(find /app/prisma/migrations -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null | sort | tail -n 1)
            
            if [ -n "$latest_migration" ]; then
                echo "⏳ Attempting to roll back failed migration: $latest_migration"
                node /app/node_modules/.bin/prisma migrate resolve --rolled-back "$latest_migration" --schema=/app/prisma/schema.prisma 2>/dev/null || true
            fi
            
            # Retry migration
            node /app/node_modules/.bin/prisma migrate deploy --schema=/app/prisma/schema.prisma
            
            if [ $? -eq 0 ]; then
                echo "✅ Dashboard migrations completed after resolution"
            else
                echo "⚠️  Dashboard migration still has issues, continuing anyway..."
            fi
        fi
    else
        echo "ℹ️  No migration files found, skipping dashboard database migrations."
    fi
else
    echo "⚠️  Database not found yet, will be created by trading bot"
    echo "   Dashboard will start anyway and wait for data..."
fi

echo "✅ Dashboard ready"

# Start Next.js server
echo "🚀 Starting Next.js server..."
exec npm start
