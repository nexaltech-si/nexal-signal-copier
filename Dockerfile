# Dockerfile for Trading Bot Main App
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# upgrade: pull Debian security fixes newer than the base image (M-10)
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Discord "own account" mode: discord.py-self uses the same package name as discord.py
# (the bot library above), so it gets its own virtualenv. The bot runs
# src/integrations/discord/user_worker.py with this interpreter.
RUN python -m venv /opt/discord-user \
    && /opt/discord-user/bin/pip install --no-cache-dir "discord.py-self==2.1.0"

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/logs /app/data /app/prisma /app/sessions

# Copy entrypoint script
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Generate Prisma client
RUN prisma generate --schema=/app/prisma/schema.prisma

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL="file:/app/data/trading_bot.db"

# Internal API for the dashboard (Telegram login lives there too)
EXPOSE 8001

# Run the entrypoint script (which handles migrations + starts bot)
ENTRYPOINT ["/app/docker-entrypoint.sh"]
