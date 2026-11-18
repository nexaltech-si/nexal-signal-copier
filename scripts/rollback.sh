#!/bin/bash
# Roll the bot and dashboard back to the images from before the last deploy.sh
# run (tagged :previous by deploy.sh).
#
#   scripts/rollback.sh
#       images only — enough when the deploy ran no migration
#
#   scripts/rollback.sh --restore-db backups/db-YYYYMMDD-HHMMSS
#       also restore the database backup deploy.sh took. Use it when the deploy
#       migrated the schema and the old code can't work with it. Everything
#       written since that backup (signals, trades, settings) is LOST.

set -eu
cd "$(dirname "$0")/.."

RESTORE_DIR=""
if [ "${1:-}" = "--restore-db" ]; then
    RESTORE_DIR="${2:?usage: scripts/rollback.sh --restore-db backups/db-YYYYMMDD-HHMMSS}"
    [ -f "$RESTORE_DIR/trading_bot.db" ] || { echo "❌ $RESTORE_DIR/trading_bot.db not found"; exit 1; }
fi

images=(nexal-trading-bot nexal-dashboard)
for image in "${images[@]}"; do
    docker image inspect "$image:previous" >/dev/null 2>&1 \
        || { echo "❌ $image:previous not found — nothing to roll back to"; exit 1; }
done

echo "⏪ Rolling back bot and dashboard to the previous images"
docker compose stop trading-bot dashboard

if [ -n "$RESTORE_DIR" ]; then
    echo "💾 Restoring database from $RESTORE_DIR (data written since then is lost)"
    docker run --rm -v trading-bot-database:/data -v "$PWD/$RESTORE_DIR":/backup:ro alpine:3.20 \
        sh -c 'rm -f /data/trading_bot.db-wal /data/trading_bot.db-shm && cp -a /backup/trading_bot.db* /data/'
fi

for image in "${images[@]}"; do
    docker tag "$image:previous" "$image:latest"
done
docker compose up -d --no-build --force-recreate trading-bot dashboard

scripts/smoke_check.sh 180
