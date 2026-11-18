#!/bin/bash
# Post-deploy smoke check: is the RUNNING system actually working?
#
# Tests prove the logic; this proves the deployment — containers stay up, the
# bot API answers, MT5 and Telegram connect, the dashboard serves, and nothing
# crashed while doing it. Run by deploy.sh after `docker compose up`, or by hand:
#
#   scripts/smoke_check.sh [timeout_seconds]      (default 180)
#
# Exit 0 = healthy (warnings allowed), 1 = something is broken.

set -u
cd "$(dirname "$0")/.."

TIMEOUT="${1:-180}"
FAILED=0

ok()   { echo "  ✅ $*"; }
warn() { echo "  ⚠️  $*"; }
fail() { echo "  ❌ $*"; FAILED=1; }

echo ""
echo "🩺 Smoke check (up to ${TIMEOUT}s)"
echo "────────────────────────────────────────"

# ── 1. Containers running and not crash-looping ──────────────────────────────
for c in telegram-trading-bot trading-dashboard trading-redis; do
    if ! state=$(docker inspect -f '{{.State.Status}} {{.RestartCount}}' "$c" 2>/dev/null); then
        fail "$c: container missing"
        continue
    fi
    status=${state% *}; restarts=${state#* }
    if [ "$status" != "running" ]; then
        fail "$c: $status"
    elif [ "$restarts" != "0" ]; then
        fail "$c: restarted $restarts time(s) since deploy (crash loop?)"
    else
        ok "$c running"
    fi
done

# ── 2. Bot: API, trading provider, Telegram, health loop ─────────────────────
# Runs inside the bot container; computes the internal API token the same way
# src/api/internal_auth.py does instead of importing the bot.
docker exec -i -e SMOKE_TIMEOUT="$TIMEOUT" telegram-trading-bot python - <<'PY'
import hashlib, hmac, json, os, sys, time, urllib.request, urllib.error

timeout = int(os.environ.get("SMOKE_TIMEOUT", "180"))
deadline = time.time() + timeout
failed = False

def say(level, msg):
    global failed
    icon = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}[level]
    print(f"  {icon} {msg}", flush=True)
    if level == "fail":
        failed = True

token = (os.environ.get("INTERNAL_API_TOKEN") or "").strip()
if not token and os.environ.get("SETTINGS_ENCRYPTION_KEY", "").strip():
    token = hmac.new(os.environ["SETTINGS_ENCRYPTION_KEY"].strip().encode(),
                     b"nexal-internal-api-v1", hashlib.sha256).hexdigest()
port = os.environ.get("API_SERVER_PORT", "8001")

def get(path):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"X-Internal-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None

# API up
while time.time() < deadline and get("/health")[0] != 200:
    time.sleep(2)
if get("/health")[0] != 200:
    say("fail", f"bot API not answering after {timeout}s")
    sys.exit(1)
say("ok", "bot API answering")

for path in ("/api/settings/metadata", "/api/provider", "/api/connections/status"):
    code, _ = get(path)
    if code == 200:
        say("ok", f"GET {path} 200")
    else:
        say("fail", f"GET {path} -> {code}")

# Trading provider and Telegram may need a little longer than the API.
provider = telegram = None
while time.time() < deadline:
    _, provider = get("/api/provider")
    _, conn = get("/api/connections/status")
    telegram = ((conn or {}).get("telegram") or {}).get("auth", {}).get("state")
    if provider and provider.get("healthy") and telegram not in (None, "starting"):
        break
    time.sleep(3)

if provider and provider.get("healthy"):
    say("ok", f"trading provider {provider.get('active')} connected and healthy")
else:
    say("fail", f"trading provider not healthy: {provider}")

if telegram == "live":
    say("ok", "Telegram logged in and listening")
elif telegram in ("logged_out", "code_sent", "password_required"):
    say("warn", "Telegram is NOT logged in — no signals until you log in (Connections → Telegram)")
elif telegram == "not_configured":
    say("warn", "Telegram is not set up (no API ID / hash) — running without it")
else:
    say("fail", f"Telegram listener state: {telegram}")

# Health loop: give it one full cycle to report
time.sleep(min(20, max(0, deadline - time.time())))
_, conn = get("/api/connections/status")
components = ((conn or {}).get("health") or {}).get("components") or {}
bad = {k: v for k, v in components.items() if v.get("status") != "healthy"}
if not components:
    say("warn", "health loop has not reported yet")
elif bad:
    for name, comp in bad.items():
        say("warn", f"health: {name} {comp.get('status')} — {comp.get('message')}")
else:
    say("ok", f"health checks all green ({', '.join(components)})")

sys.exit(1 if failed else 0)
PY
[ $? -eq 0 ] || FAILED=1

# ── 3. Dashboard serves pages and enforces auth ──────────────────────────────
docker exec -i trading-dashboard node - <<'JS' || FAILED=1
const deadline = Date.now() + 90_000
const get = (p) => fetch('http://127.0.0.1:3000' + p, { redirect: 'manual' }).then(r => r.status).catch(() => null)
;(async () => {
  let page = null
  while (Date.now() < deadline && !(page = await get('/sign-in'))) await new Promise(r => setTimeout(r, 2000))
  let failed = false
  if (page === 200) console.log('  ✅ dashboard serves pages')
  else { console.log(`  ❌ dashboard /sign-in -> ${page}`); failed = true }
  const api = await get('/api/connections')
  if (api === 401) console.log('  ✅ dashboard API requires login')
  else { console.log(`  ❌ dashboard /api/connections without login -> ${api} (expected 401)`); failed = true }
  process.exit(failed ? 1 : 0)
})()
JS

# ── 4. Nothing crashed while starting ────────────────────────────────────────
bot_since=$(docker inspect -f '{{.State.StartedAt}}' telegram-trading-bot 2>/dev/null)
dash_since=$(docker inspect -f '{{.State.StartedAt}}' trading-dashboard 2>/dev/null)
bot_logs=$(docker logs --since "$bot_since" telegram-trading-bot 2>&1)
dash_logs=$(docker logs --since "$dash_since" trading-dashboard 2>&1)

asgi=$(grep -c "Exception in ASGI application" <<<"$bot_logs")
critical=$(grep -c "| CRITICAL" <<<"$bot_logs")
tracebacks=$(grep -c "^Traceback" <<<"$bot_logs")
prisma=$(grep -cE "PrismaClient[A-Za-z]*Error|code: 'P[0-9]{4}'" <<<"$dash_logs")

if [ "$asgi" != "0" ]; then
    fail "bot API raised $asgi unhandled exception(s) — an endpoint is broken:"
    grep -A60 "Exception in ASGI application" <<<"$bot_logs" | grep -E "^\w*Error|^\w+Exception|File \"/app" | head -6 | sed 's/^/      /'
else
    ok "no unhandled API exceptions"
fi
[ "$critical" != "0" ] && fail "bot logged $critical CRITICAL line(s)"
[ "$prisma" != "0" ] && fail "dashboard hit $prisma database error(s) (schema/migration mismatch?)" \
    && grep -E "PrismaClient[A-Za-z]*Error|code: 'P[0-9]{4}'|does not exist" <<<"$dash_logs" | head -3 | sed 's/^/      /'
[ "$tracebacks" != "0" ] && warn "bot logged $tracebacks traceback(s) since start — review: docker logs telegram-trading-bot"

echo "────────────────────────────────────────"
if [ "$FAILED" = "0" ]; then
    echo "✅ Smoke check passed"
    exit 0
fi
echo "❌ Smoke check FAILED"
exit 1
