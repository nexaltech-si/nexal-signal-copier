#!/bin/bash
# Rotate the MT5 REST bridge API key everywhere it is used:
#
#   mt5/.env           MT5_API_KEY        the bridge (requires it since audit C-01)
#   .env               MT5_REST_API_KEY   dashboard env, scripts (redis publisher, MCP)
#   settings database  MT5_REST_API_KEY   the bot (encrypted secret)
#
# Order matters (2026-10-15): the bridge gets the new key first; the bot's copy is
# changed only once the bridge accepts it, so the bot's live reload can verify and
# adopt it without a restart. The dashboard is recreated last to load its env.
#
#   scripts/rotate_mt5_key.sh            generate a new random key
#
# The key is never printed or put on a command line. Read it later with:
#   grep ^MT5_API_KEY= mt5/.env
# The MT5 terminal restarts (~2 min): the bot can't trade meanwhile.

set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] && [ -f mt5/.env ] || { echo "❌ .env or mt5/.env missing"; exit 1; }

TS=$(date +%Y%m%d-%H%M%S)
mkdir -p "backups/env-$TS" && chmod 700 backups "backups/env-$TS"
cp -p .env "backups/env-$TS/root.env" && cp -p mt5/.env "backups/env-$TS/mt5.env"
chmod 600 "backups/env-$TS"/*
echo "💾 Previous .env files saved to backups/env-$TS"

KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')

set_line() {  # file var value — replace the line, or append it
    local file=$1 var=$2 value=$3
    if grep -q "^$var=" "$file"; then
        python3 -c '
import sys
path, var = sys.argv[1], sys.argv[2]
value = sys.stdin.read().strip()
lines = open(path).read().split("\n")
open(path, "w").write("\n".join(f"{var}={value}" if l.startswith(var + "=") else l for l in lines))' "$file" "$var" <<<"$value"
    else
        printf '\n%s=%s\n' "$var" "$value" >> "$file"
    fi
}
set_line mt5/.env MT5_API_KEY "$KEY"
set_line .env MT5_REST_API_KEY "$KEY"
echo "🔑 New key written to mt5/.env and .env"

echo "🔄 Restarting the MT5 bridge with the new key (terminal ~2 min)..."
(cd mt5 && docker compose up -d --no-build --force-recreate)
for i in $(seq 1 120); do
    # header via a curl config on stdin: the key never appears in a process list
    code=$(curl -s -o /dev/null -w '%{http_code}' -K - http://127.0.0.1:5002/terminal_info <<<"header = \"X-API-Key: $KEY\"" || true)
    [ "$code" = "200" ] && break
    sleep 5
done
[ "$code" = "200" ] || { echo "❌ Bridge did not accept the new key within 10 min (last HTTP $code). Bot and dashboard not changed."; exit 1; }
echo "✅ Bridge accepts the new key"

echo "🤖 Giving the bot the new key (live, no restart)..."
docker exec -i -w /app telegram-trading-bot python - <<PY
import asyncio, hashlib, hmac, json, os, sys, urllib.request
from loguru import logger
logger.remove()
from src.core.prisma_client import prisma_client
from src.services.settings_service import SettingsService

async def main():
    await prisma_client.initialize()
    svc = SettingsService(prisma_client.client, encryption_key=os.environ["SETTINGS_ENCRYPTION_KEY"])
    if not await svc.set_setting("MT5_REST_API_KEY", """$KEY"""):
        sys.exit("setting MT5_REST_API_KEY not found")
    token = os.environ.get("INTERNAL_API_TOKEN") or hmac.new(
        os.environ["SETTINGS_ENCRYPTION_KEY"].encode(), b"nexal-internal-api-v1", hashlib.sha256).hexdigest()
    req = urllib.request.Request("http://127.0.0.1:8001/api/settings/reload", method="POST",
                                 headers={"X-Internal-Token": token})
    print("   settings reload:", json.loads(urllib.request.urlopen(req, timeout=60).read()).get("success"))
asyncio.run(main())
PY
unset KEY

echo "🖥️  Restarting the dashboard to load the new key..."
docker compose up -d --no-build --no-deps --force-recreate dashboard

bash scripts/smoke_check.sh 180
