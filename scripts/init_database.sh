#!/bin/sh
# Bring the database schema up to date. Runs inside the bot image (deploy.sh and
# docker-entrypoint.sh call it); safe to run every start.
#
#   fresh database  -> create every table from prisma/schema.prisma, record all
#                      shipped migrations as applied (they are incremental changes
#                      to an existing database and cannot build one from nothing),
#                      then import the starting settings from .env.
#   existing one    -> apply pending migrations (prisma migrate deploy).
#
# Exit 0 = schema ready, non-zero = it is not (do not start the bot).

SCHEMA="${PRISMA_SCHEMA:-/app/prisma/schema.prisma}"
MIGRATIONS="$(dirname "$SCHEMA")/migrations"
DB_FILE="${DATABASE_URL#file:}"

is_fresh() {
    [ ! -s "$DB_FILE" ] && return 0
    python3 - "$DB_FILE" <<'PY'
import sqlite3, sys
try:
    tables = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True).execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name != '_prisma_migrations'").fetchone()[0]
except sqlite3.Error:
    tables = 1   # unreadable: not ours to initialise, let prisma report it
sys.exit(0 if tables == 0 else 1)
PY
}

if is_fresh; then
    echo "🆕 Empty database — creating all tables from the schema..."
    mkdir -p "$(dirname "$DB_FILE")"
    prisma db push --schema="$SCHEMA" --skip-generate || exit 1
    for dir in "$MIGRATIONS"/*/; do
        [ -f "${dir}migration.sql" ] || continue
        name="$(basename "$dir")"
        prisma migrate resolve --applied "$name" --schema="$SCHEMA" >/dev/null || exit 1
        echo "   recorded migration $name"
    done
    echo "✅ Database created"
    # Once, on a new database: take the settings given in .env (trading provider, AI
    # provider, risk limits...) as the starting values. Later changes go through the dashboard.
    if [ -f "$(dirname "$0")/init_settings_from_env.py" ] && [ "${SKIP_ENV_IMPORT:-}" != "1" ]; then
        echo "📥 Importing the starting settings from .env..."
        python3 "$(dirname "$0")/init_settings_from_env.py" 2>&1 | grep -E "Found|Successfully|rror|Traceback" \
            || echo "⚠️  Could not import .env settings — set them in the dashboard instead"
    fi
else
    echo "📊 Applying pending database migrations..."
    prisma migrate deploy --schema="$SCHEMA" || exit 1
    echo "✅ Database up to date"
fi
