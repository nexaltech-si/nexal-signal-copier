#!/bin/bash
# Prisma Setup Script for Trading Bot

echo "🔧 Setting up Prisma ORM..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    exit 1
fi

echo "📦 Installing Prisma Client Python..."
python3 -m pip install prisma

echo "🗄️  Generating Prisma Client..."
prisma generate

echo "📊 Running database migrations..."
prisma db push

echo "✅ Prisma setup complete!"
echo ""
echo "Next steps:"
echo "1. Update your .env file with DATABASE_URL"
echo "2. Run: python3 main.py"
