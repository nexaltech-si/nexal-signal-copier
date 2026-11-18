#!/bin/bash
# Pre-deploy checks, run against the freshly BUILT images while the old
# containers keep running — a failure here costs no downtime.
#
#   1. Test suite inside the new bot image (exactly the code that will ship)
#   2. Dashboard type-check (next build ignores type errors, see next.config)
#   3. Migration rehearsal: apply pending migrations to a copy of the live
#      database, then check both Prisma schemas against the result
#      (scripts/schema_drift.py) — catches failing migrations and fields added
#      to a schema without a migration
#
# Called by deploy.sh after `docker compose build`. Skip a step with
# SKIP_TESTS=1 / SKIP_TYPECHECK=1 / SKIP_MIGRATION_REHEARSAL=1.

set -u
cd "$(dirname "$0")/.."

BOT_IMAGE="nexal-trading-bot:latest"
DB_VOLUME="trading-bot-database"
FAILED=0

echo ""
echo "🧪 Preflight (live system untouched)"
echo "────────────────────────────────────────"

# ── 1. Tests ──────────────────────────────────────────────────────────────────
if [ "${SKIP_TESTS:-}" = "1" ]; then
    echo "  ⚠️  SKIP_TESTS=1 — tests skipped"
elif ! ls tests/test_*.py >/dev/null 2>&1; then
    echo "  ⚠️  no tests/ directory in this release — test step skipped"
else
    echo "  → test suite (new bot image)..."
    out=$(docker run --rm --network none --env-file .env \
            -e DATABASE_URL=file:/tmp/preflight-test.db \
            -v "$PWD/tests":/app/tests:ro -w /app \
            --entrypoint python "$BOT_IMAGE" -m pytest -q -p no:cacheprovider tests 2>&1)
    if [ $? -eq 0 ]; then
        echo "  ✅ $(tail -1 <<<"$out")"
    else
        echo "  ❌ tests failed:"
        grep -E "^(FAILED|ERROR)|passed|failed|error" <<<"$out" | tail -15 | sed 's/^/      /'
        FAILED=1
    fi
fi

# ── 2. Dashboard type-check ───────────────────────────────────────────────────
if [ "${SKIP_TYPECHECK:-}" = "1" ]; then
    echo "  ⚠️  SKIP_TYPECHECK=1 — type-check skipped"
elif [ ! -d dashboard/node_modules ]; then
    echo "  ⚠️  dashboard/node_modules missing — type-check skipped (run npm ci in dashboard/)"
else
    echo "  → dashboard type-check..."
    # .next/types holds generated route types from local builds; they go stale.
    errors=$(docker run --rm -v "$PWD/dashboard":/app -w /app node:22-bookworm-slim \
               npx tsc --noEmit -p tsconfig.json 2>&1 | grep "error TS" | grep -v "^\.next/")
    if [ -z "$errors" ]; then
        echo "  ✅ no type errors"
    else
        echo "  ❌ $(wc -l <<<"$errors") type error(s):"
        head -10 <<<"$errors" | sed 's/^/      /'
        FAILED=1
    fi
fi

# ── 3. Migration rehearsal on a copy of the live database ─────────────────────
if [ "${SKIP_MIGRATION_REHEARSAL:-}" = "1" ]; then
    echo "  ⚠️  SKIP_MIGRATION_REHEARSAL=1 — migration rehearsal skipped"
elif ! docker volume inspect "$DB_VOLUME" >/dev/null 2>&1; then
    echo "  ⚠️  no $DB_VOLUME volume yet (first deploy) — migration rehearsal skipped"
else
    echo "  → migration rehearsal on a copy of the live database..."
    out=$(docker run --rm --network none \
            -v "$DB_VOLUME":/live:ro \
            -v "$PWD/dashboard/prisma/schema.prisma":/tmp/dashboard.prisma:ro \
            -v "$PWD/scripts/schema_drift.py":/tmp/schema_drift.py:ro \
            -e DATABASE_URL=file:/tmp/rehearsal.db -w /app \
            --entrypoint sh "$BOT_IMAGE" -c '
              python - <<PY || exit 3
import sqlite3
src = sqlite3.connect("file:/live/trading_bot.db?mode=ro", uri=True)
dst = sqlite3.connect("/tmp/rehearsal.db"); src.backup(dst); dst.close()
PY
              prisma migrate deploy --schema=/app/prisma/schema.prisma >/tmp/migrate.log 2>&1
              migrate_rc=$?
              grep -E "Applying|No pending" /tmp/migrate.log
              if [ $migrate_rc -ne 0 ]; then tail -8 /tmp/migrate.log | sed "s/^/❌ /"; exit 4; fi
              python /tmp/schema_drift.py /tmp/rehearsal.db /app/prisma/schema.prisma /tmp/dashboard.prisma
            ' 2>&1)
    rc=$?
    grep -E "Applying" <<<"$out" | sed 's/^/      /'
    if [ $rc -eq 0 ]; then
        echo "  ✅ migrations apply cleanly and the database matches both schemas"
    else
        case $rc in
            3) echo "  ❌ could not copy the live database for the rehearsal" ;;
            4) echo "  ❌ migrations FAILED on the copy — the real deploy would fail the same way:" ;;
            *) echo "  ❌ schema drift — a schema expects tables/columns no migration creates:" ;;
        esac
        grep -E "❌|Error|error" <<<"$out" | head -10 | sed 's/^/      /'
        FAILED=1
    fi
fi

echo "────────────────────────────────────────"
if [ "$FAILED" = "0" ]; then
    echo "✅ Preflight passed"
    exit 0
fi
echo "❌ Preflight FAILED — nothing was stopped or changed"
exit 1
