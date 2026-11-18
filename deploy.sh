#!/bin/bash

# Deployment script. First install:  ./deploy.sh --init   (see AGENTS.md / README.md)
# Every later update:                ./deploy.sh

set -e

# ── Flag parsing ───────────────────────────────────────────────────────────────
INIT_MODE=false
for arg in "$@"; do
  [[ "$arg" == "-init" || "$arg" == "--init" ]] && INIT_MODE=true
done

# ── Helpers ────────────────────────────────────────────────────────────────────
# set_env KEY VALUE [FILE] — set KEY in an env file (replace the line, or append it).
# Goes through awk's ENVIRON so that values with |, &, / or \ are written unchanged.
set_env() {
    local key="$1" file="${3:-.env}"
    SET_ENV_VALUE="$2" awk -v key="$key" '
        BEGIN { value = ENVIRON["SET_ENV_VALUE"]; done = 0 }
        index($0, key "=") == 1 && !done { print key "=" value; done = 1; next }
        { print }
        END { if (!done) print key "=" value }
    ' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
}

get_env() {  # get_env KEY [FILE] — value without an inline "# comment"
    grep -m1 "^$1=" "${2:-.env}" 2>/dev/null | cut -d'=' -f2- | sed 's/[[:space:]]*#.*$//; s/^"//; s/"$//'
}

random_key() {  # 32 random bytes, url-safe base64 (the format Fernet expects)
    python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())" 2>/dev/null \
        || openssl rand -base64 32 | tr '+/' '-_'
}

ensure_networks() {
    # traefik-public: only used when a Traefik reverse proxy runs on this host, but
    # docker-compose.yml lists it as external, so it has to exist.
    # mt5-net: shared with the MT5 container (mt5/docker-compose.yml creates it too).
    local net
    for net in traefik-public mt5-net; do
        docker network inspect "$net" >/dev/null 2>&1 || { docker network create "$net" >/dev/null && echo "  ✅ Created Docker network: $net"; }
    done
}

section() {
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo " $1"
    [ -n "${2:-}" ] && echo " $2"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# ── MT5 container (self-hosted broker connection) ──────────────────────────────
# Started BEFORE the bot: it owns the mt5-net network and the bot connects to it.
setup_mt5_container() {
    if [ ! -f mt5/docker-compose.yml ]; then
        echo "  ⚠️  mt5/ is not in this checkout — point MT5_REST_API_URL at your own MT5 REST API."
        return
    fi
    [ -f mt5/.env ] || cp mt5/.env.example mt5/.env
    chmod 600 mt5/.env

    local key; key="$(get_env MT5_API_KEY mt5/.env)"
    [ -n "$key" ] || key="$(random_key)"
    set_env MT5_API_KEY "$key" mt5/.env
    set_env MT5_REST_API_URL "http://mt5:5001"
    set_env MT5_REST_API_KEY "$key"
    echo "  🔑 API key for the MT5 bridge generated and written to mt5/.env and .env"
    echo ""

    echo "  The MT5 terminal runs in a browser desktop (VNC). Choose its login:"
    read -rp  "  VNC user     (default: admin): " vnc_user
    read -rsp "  VNC password (hidden, required): " vnc_pass; echo ""
    set_env CUSTOM_USER "${vnc_user:-admin}" mt5/.env
    [ -n "$vnc_pass" ] && set_env PASSWORD "$vnc_pass" mt5/.env
    echo ""
    echo "  Broker account (optional — press Enter to log in later inside the terminal):"
    read -rp  "  MT5 login (account number): " mt5_login
    if [ -n "$mt5_login" ]; then
        read -rsp "  MT5 password (hidden):      " mt5_pass; echo ""
        read -rp  "  MT5 server (e.g. Broker-Demo): " mt5_server
        set_env MT5_LOGIN "$mt5_login" mt5/.env
        set_env MT5_PASSWORD "$mt5_pass" mt5/.env
        set_env MT5_SERVER "$mt5_server" mt5/.env
        set_env MT5_PERSIST_LOGIN 1 mt5/.env
    fi
    echo ""
    read -rp "  Build and start the MT5 container now? The first build downloads several GB. [Y/n]: " start_mt5
    if [[ ! "$start_mt5" =~ ^[Nn]$ ]]; then
        docker network inspect mt5-net >/dev/null 2>&1 || docker network create mt5-net >/dev/null
        (cd mt5 && docker compose up -d --build) || { echo "  ❌ MT5 container failed to start — fix it, then re-run ./deploy.sh --init"; exit 1; }
        echo ""
        echo "  ✅ MT5 container started. Before the bot can trade:"
        echo "     1. Open the terminal: http://127.0.0.1:3001 on this server"
        echo "        (from your computer: ssh -L 3001:127.0.0.1:3001 <user>@<server>)"
        echo "     2. Log in to your broker account and switch on the 'Algo Trading' button."
    else
        echo "  ⏭  Start it later with:  docker network create mt5-net; (cd mt5 && docker compose up -d --build)"
    fi
    echo ""
}

# ── First-time setup wizard ────────────────────────────────────────────────────
init_setup() {
    echo ""
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║            🚀  First-Time Setup                       ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo ""
    echo "This wizard will:"
    echo "  1. Create .env and generate the encryption key"
    echo "  2. Set up the trading connection (and start the MT5 container first, if you use it)"
    echo "  3. Ask for the signal source, AI and dashboard login credentials"
    echo "  4. Create the Docker networks, the database, and start all services"
    echo ""
    echo "Everything it asks for can be changed later in .env or in the dashboard."
    echo ""

    # ── .env handling ──────────────────────────────────────────────────────────
    if [ -f ".env" ]; then
        echo "⚠️  A .env file already exists."
        read -rp "   Reconfigure credentials? Values you skip are kept. [y/N]: " reconfigure
        if [[ ! "$reconfigure" =~ ^[Yy]$ ]]; then
            echo "   Skipping wizard — using existing .env"
            echo ""
            return
        fi
        echo ""
    else
        if [ ! -f ".env.example" ]; then
            echo "❌ .env.example not found — cannot generate .env"
            exit 1
        fi
        cp .env.example .env
    fi
    chmod 600 .env

    # Encryption key: generated once, never replaced (saved secrets depend on it)
    if [ -z "$(get_env SETTINGS_ENCRYPTION_KEY)" ]; then
        set_env SETTINGS_ENCRYPTION_KEY "$(random_key)"
        echo "🔑 Generated SETTINGS_ENCRYPTION_KEY (stored in .env — back that file up)."
        echo ""
    fi

    section "Step 1 of 5 — Trading connection"
    echo "  [1] MetaAPI  — cloud connection to your broker account (metaapi.cloud)"
    echo "  [2] MT5 REST — self-hosted MetaTrader 5 in a container on this server"
    echo "  [3] None yet — detect signals only, place no trades"
    echo ""
    read -rp "  Choose [1/2/3] (default: 1): " provider_choice
    echo ""
    case "$provider_choice" in
        2)
            TRADING_PROVIDER="mt5rest"
            set_env TRADING_PROVIDER mt5rest
            read -rp "  Use the MT5 container that ships in mt5/ ? [Y/n]: " bundled
            echo ""
            if [[ "$bundled" =~ ^[Nn]$ ]]; then
                read -rp  "  MT5_REST_API_URL (e.g. http://mt5:5001): " MT5_URL
                read -rsp "  MT5_REST_API_KEY (hidden input):          " MT5_KEY; echo ""
                [ -n "$MT5_URL" ] && set_env MT5_REST_API_URL "$MT5_URL"
                [ -n "$MT5_KEY" ] && set_env MT5_REST_API_KEY "$MT5_KEY"
            else
                setup_mt5_container
            fi
            ;;
        3)
            TRADING_PROVIDER="none"
            set_env SKIP_METAAPI true
            echo "  Trading is switched off (SKIP_METAAPI=true). Turn it on later in the dashboard:"
            echo "  AI & Bot → System → Disable Trading, then restart the bot."
            ;;
        *)
            TRADING_PROVIDER="metaapi"
            set_env TRADING_PROVIDER metaapi
            read -rsp "  METAAPI_TOKEN      (hidden input): " META_TOKEN; echo ""
            read -rp  "  METAAPI_ACCOUNT_ID (e.g. abc-123): " META_ACCOUNT
            [ -n "$META_TOKEN" ]   && set_env METAAPI_TOKEN "$META_TOKEN"
            [ -n "$META_ACCOUNT" ] && set_env METAAPI_ACCOUNT_ID "$META_ACCOUNT"
            ;;
    esac
    echo ""

    section "Step 2 of 5 — Signal source: Telegram (optional)" \
            "API ID and hash: https://my.telegram.org → API development tools. Enter = skip."
    echo "  Discord is set up later on the dashboard's Discord page; nothing is needed here."
    echo ""
    read -rp  "  TELEGRAM_API_ID   (e.g. 12345678): " TG_API_ID
    if [ -n "$TG_API_ID" ]; then
        read -rsp "  TELEGRAM_API_HASH (hidden input):  " TG_API_HASH; echo ""
        read -rp  "  TELEGRAM_PHONE    (e.g. +1234567890): " TG_PHONE
        set_env TELEGRAM_API_ID "$TG_API_ID"
        [ -n "$TG_API_HASH" ] && set_env TELEGRAM_API_HASH "$TG_API_HASH"
        [ -n "$TG_PHONE" ]    && set_env TELEGRAM_PHONE "$TG_PHONE"
    else
        echo "  ⏭  Skipped — the bot runs without Telegram until you add it (.env or AI & Bot → Telegram)."
    fi
    echo ""

    section "Step 3 of 5 — AI provider (reads the signals)"
    echo "  [1] DeepSeek — fast and cheap"
    echo "  [2] OpenAI"
    echo "  [3] Ollama   — local model, no API key"
    echo ""
    read -rp "  Choose [1/2/3] (default: 1): " ai_choice
    echo ""
    case "$ai_choice" in
        2)
            read -rsp "  OPENAI_API_KEY (hidden input): " OAI_KEY; echo ""
            [ -n "$OAI_KEY" ] && set_env OPENAI_API_KEY "$OAI_KEY"
            set_env PRIMARY_AI_PROVIDER openai
            ;;
        3)
            read -rp "  OLLAMA_URL (default: http://host.docker.internal:11434): " OLLAMA_URL_VAL
            set_env OLLAMA_URL "${OLLAMA_URL_VAL:-http://host.docker.internal:11434}"
            set_env PRIMARY_AI_PROVIDER ollama
            ;;
        *)
            read -rsp "  DEEPSEEK_API_KEY (hidden input): " DS_KEY; echo ""
            [ -n "$DS_KEY" ] && set_env DEEPSEEK_API_KEY "$DS_KEY"
            set_env PRIMARY_AI_PROVIDER deepseek
            ;;
    esac
    echo "  Chart images need a vision-capable provider (OpenAI, Gemini, …): add its key later under AI & Bot → AI."
    echo ""

    section "Step 4 of 5 — Dashboard login (Clerk)" \
            "Create a free application at https://dashboard.clerk.com → API keys."
    read -rp  "  NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY (pk_...): " CLERK_PK
    read -rsp "  CLERK_SECRET_KEY (sk_..., hidden):          " CLERK_SK; echo ""
    [ -n "$CLERK_PK" ] && set_env NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY "$CLERK_PK"
    [ -n "$CLERK_SK" ] && set_env CLERK_SECRET_KEY "$CLERK_SK"
    echo ""
    echo "  Only ONE Clerk user may use the dashboard. If you already have your user id"
    echo "  (user_..., Clerk → Users) enter it; otherwise press Enter and follow the note at the end."
    read -rp  "  AUTHORIZED_USER_ID: " OWNER_ID
    [ -n "$OWNER_ID" ] && set_env AUTHORIZED_USER_ID "$OWNER_ID"
    echo ""

    section "Step 5 of 5 — Notifications (optional, Enter = skip)"
    read -rsp "  TELEGRAM_BOT_TOKEN            (hidden, from @BotFather): " BOT_TOKEN; echo ""
    read -rp  "  TELEGRAM_NOTIFICATION_CHAT_ID (your chat id, from @userinfobot): " NOTIF_CHAT
    [ -n "$BOT_TOKEN" ]  && set_env TELEGRAM_BOT_TOKEN "$BOT_TOKEN"
    [ -n "$NOTIF_CHAT" ] && set_env TELEGRAM_NOTIFICATION_CHAT_ID "$NOTIF_CHAT"
    echo ""

    # ── Validate ───────────────────────────────────────────────────────────────
    echo "🔍 Checking the configuration..."
    VALIDATION_FAILED=false
    _require() {  # _require VAR "why it is needed"
        if [ -z "$(get_env "$1")" ]; then
            echo "  ❌ $1 is empty — $2"
            VALIDATION_FAILED=true
        else
            echo "  ✅ $1"
        fi
    }
    _require SETTINGS_ENCRYPTION_KEY "the bot does not start without it"
    _require NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY "the dashboard cannot be built or opened without it"
    _require CLERK_SECRET_KEY "the dashboard login does not work without it"
    case "$TRADING_PROVIDER" in
        metaapi) _require METAAPI_TOKEN "needed to reach your broker account"
                 _require METAAPI_ACCOUNT_ID "needed to reach your broker account" ;;
        mt5rest) _require MT5_REST_API_KEY "the MT5 bridge rejects requests without it" ;;
    esac
    [ -n "$(get_env TELEGRAM_API_ID)" ] && _require TELEGRAM_API_HASH "Telegram needs the hash together with the API ID"
    echo ""

    if [[ "$VALIDATION_FAILED" == "true" ]]; then
        echo "⚠️  Fill in the missing values, then run ./deploy.sh (or the wizard again: ./deploy.sh --init)"
        echo "   nano .env"
        echo ""
        exit 1
    fi

    if [ -z "$(get_env AUTHORIZED_USER_ID)" ]; then
        NEEDS_OWNER_ID=true
    fi
    echo "✅ Configuration complete — starting deployment..."
    echo ""
}

# ── Main banner ────────────────────────────────────────────────────────────────
if [ "$INIT_MODE" = "true" ]; then
    echo "🚀 First-Time Setup + Deployment"
    echo "==============================="
else
    echo "🚀 Deployment"
    echo "============="
fi
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed!"
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    echo "✅ Docker installed. Please log out and back in, then run this script again."
    exit 1
fi

# Check if Docker Compose is available
if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not available!"
    echo "Installing Docker Compose plugin..."
    sudo apt update
    sudo apt install -y docker-compose-plugin
fi

echo "✅ Docker and Docker Compose are installed"
echo ""

# Run first-time setup wizard if -init flag was passed
if [ "$INIT_MODE" = "true" ]; then
    init_setup
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found!"
    echo "Creating .env from .env.example..."
    
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✅ Created .env file"
        echo ""
        echo "⚠️  IMPORTANT: Edit .env file with your credentials:"
        echo "   nano .env"
        echo ""
        echo "Required: SETTINGS_ENCRYPTION_KEY, the Clerk keys, a trading connection"
        echo "(METAAPI_* or MT5_REST_*) and an AI key. The wizard fills them in for you:"
        echo "   ./deploy.sh --init"
        echo ""
        read -p "Press Enter after editing .env file..."
    else
        echo "❌ .env.example not found! Cannot create .env"
        exit 1
    fi
else
    echo "✅ .env file found"
fi

echo ""

if [ -z "$(get_env SETTINGS_ENCRYPTION_KEY)" ]; then
    echo "❌ SETTINGS_ENCRYPTION_KEY is empty in .env — the bot does not start without it."
    echo "   Run ./deploy.sh --init, or generate one:"
    echo "   python3 -c \"import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())\""
    exit 1
fi

echo "🌐 Docker networks..."
ensure_networks
mkdir -p sessions logs data
echo ""

# ── Security audit ────────────────────────────────────────────────────────────
if [ "${SKIP_SECURITY_AUDIT}" = "1" ]; then
  echo "⚠️  SKIP_SECURITY_AUDIT=1 — skipping security checks (not recommended for production)"
  echo ""
else
  bash "$(dirname "$0")/security-audit.sh" || exit 1
fi

BOT_IMAGE=nexal-trading-bot
DASH_IMAGE=nexal-dashboard

# ── Build (old containers keep running) ───────────────────────────────────────
# Keep the running images as :previous so scripts/rollback.sh can restore them.
for image in $BOT_IMAGE $DASH_IMAGE; do
    docker image inspect "$image:latest" >/dev/null 2>&1 && docker tag "$image:latest" "$image:previous"
done

echo "📦 Building images (services keep running)..."
# --pull: without it the build reuses whatever base image is cached here, so
# Node/Python/Debian security releases never reach the app (Node 22.23.4, Oct 2026).
docker compose build --pull

# ── Preflight: tests, type-check, migration rehearsal — still no downtime ─────
if ! bash "$(dirname "$0")/scripts/preflight.sh"; then
    # Point :latest back at what is running, so a later `docker compose up`
    # doesn't start the image that just failed.
    for image in $BOT_IMAGE $DASH_IMAGE; do
        docker image inspect "$image:previous" >/dev/null 2>&1 && docker tag "$image:previous" "$image:latest"
    done
    echo ""
    echo "❌ Deploy aborted before any downtime — the running system is unchanged."
    exit 1
fi

# ── Switch over ───────────────────────────────────────────────────────────────
# Stop existing containers WITHOUT removing volumes
# IMPORTANT: Never use 'docker compose down -v' as it deletes database!
if docker compose ps -q | grep -q .; then
    echo ""
    echo "⏹️  Stopping existing containers (preserving database)..."
    docker compose stop
fi

# Back up the SQLite database before migrations change it (audit finding
# M-12). Containers are stopped, so the copy is consistent. Keeps the last
# BACKUP_KEEP (default 14) backups in ./backups (git-ignored, mode 700).
BACKUP_DIR=""
if docker volume inspect trading-bot-database >/dev/null 2>&1; then
    BACKUP_DIR="backups/db-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BACKUP_DIR" && chmod 700 backups
    if docker run --rm -v trading-bot-database:/data:ro -v "$PWD/$BACKUP_DIR":/backup alpine:3.20 \
        sh -c 'cp -a /data/trading_bot.db* /backup/ 2>/dev/null; ls /backup/trading_bot.db >/dev/null'; then
        echo "💾 Database backed up to $BACKUP_DIR"
        ls -1dt backups/db-* | tail -n +$(( ${BACKUP_KEEP:-14} + 1 )) | xargs -r rm -rf
    else
        echo "❌ Database backup failed — aborting deploy (set SKIP_DB_BACKUP=1 to override)"
        [ "${SKIP_DB_BACKUP}" = "1" ] || { docker compose start; exit 1; }
    fi
fi

# Migrate while nothing has the database open: Prisma's SQLite migrations fail
# with "database is locked" as soon as the bot or dashboard is connected
# (2026-10-14). The preflight already applied them to a copy of this database.
echo ""
echo "🔄 Preparing the database (services stopped): created on a first install, migrated otherwise..."
if docker compose run --rm --no-deps -T --entrypoint sh trading-bot /app/scripts/init_database.sh; then
    echo "✅ Database ready"
else
    echo "❌ Database migration failed — not starting the new version."
    echo "   Restore the old system:  scripts/rollback.sh --restore-db $BACKUP_DIR"
    exit 1
fi

echo ""
echo "🚀 Starting services..."
docker compose up -d --no-build --force-recreate

# ── Smoke check: is the running system actually working? ──────────────────────
if [ "${SKIP_SMOKE_CHECK:-}" = "1" ]; then
    echo "⚠️  SKIP_SMOKE_CHECK=1 — not verifying the running system"
elif ! bash "$(dirname "$0")/scripts/smoke_check.sh" 180; then
    echo ""
    echo "████████████████████████████████████████████████████████████"
    echo "❌ DEPLOY FAILED — the new version is running but BROKEN."
    echo "   Logs:      docker compose logs --tail 200 trading-bot"
    echo "   Roll back: scripts/rollback.sh"
    if [ -n "$BACKUP_DIR" ]; then
        echo "   If this deploy changed the database schema, roll back with:"
        echo "              scripts/rollback.sh --restore-db $BACKUP_DIR"
        echo "              (loses data written since the backup)"
    fi
    echo "████████████████████████████████████████████████████████████"
    exit 1
fi

echo ""
docker compose ps
echo ""
echo "🎉 Deployment successful!"
echo ""
echo "  Logs:      docker compose logs -f trading-bot"
echo "  Roll back: scripts/rollback.sh   (previous images are tagged :previous)"
echo "  Stop:      docker compose stop   (preserves the database)"
echo "  ⚠️  NEVER use 'docker compose down -v' — it DELETES your database!"
echo ""
echo "  Dashboard: http://localhost:$(get_env DASHBOARD_PORT | grep . || echo 3000)  (on this server; from elsewhere use an SSH tunnel or your reverse proxy)"
if [ "${NEEDS_OWNER_ID:-}" = "true" ] || [ -z "$(get_env AUTHORIZED_USER_ID)" ]; then
    echo ""
    echo "  👤 One step left — tell the dashboard who its owner is:"
    echo "     1. Open the dashboard and sign up."
    echo "     2. Copy your user id (user_...) from https://dashboard.clerk.com → Users."
    echo "     3. Put it in .env as AUTHORIZED_USER_ID=user_..., then: docker compose up -d dashboard"
fi
echo ""
