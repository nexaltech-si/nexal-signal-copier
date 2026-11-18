# Installation guide for AI agents (and humans in a hurry)

This file tells an agent how to install NEXAL on a fresh Linux server, in the
order that works, with a check after every step. Follow the steps in order; do
not skip the checks.

## Rules before you start

1. **Ask the human for every credential.** Never invent, guess or reuse keys.
   The list of what you need is in step 0.
2. **Never print secrets** (keys, tokens, passwords) into the chat or into logs.
   Write them only into `.env` / `mt5/.env` (both are git-ignored, mode 600).
3. **Never run `docker compose down -v`.** It deletes the database volume.
   `docker compose stop` and `docker compose down` are safe.
4. **Never change `SETTINGS_ENCRYPTION_KEY` after the first start.** Every secret
   saved in the database is encrypted with it.
5. **Do not switch on live trading yourself.** Install with a demo account or with
   trading off, and let the human decide when real orders may be placed.
6. This software places real orders on a real account. If a check fails, stop and
   report; do not work around it.

## What gets installed

| Part | Where | What it does |
|---|---|---|
| MT5 bridge (optional) | `mt5/` — container `mt5` | MetaTrader 5 terminal + REST API. Only for the self-hosted trading connection. |
| Bot | `.` — container `telegram-trading-bot` | Reads Telegram/Discord signals, runs the AI, places and manages trades. API on `127.0.0.1:8001`. |
| Dashboard | `dashboard/` — container `trading-dashboard` | Web UI on `127.0.0.1:3000`. All settings are edited here. |
| Redis | container `trading-redis` | Live prices and notifications. |
| Database | Docker volume `trading-bot-database` | One SQLite file shared by bot and dashboard. |

Two Docker networks connect them: `mt5-net` (bot ↔ MT5 bridge) and
`traefik-public` (only used if a Traefik reverse proxy runs on the host, but it
must exist).

## Step 0 — Collect what you need

Ask the human for these before touching the server.

| Needed for | Values | Where they come from |
|---|---|---|
| Dashboard login (**required**) | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` | Free application at https://dashboard.clerk.com → API keys |
| Trading connection (**one of**) | MetaAPI: `METAAPI_TOKEN`, `METAAPI_ACCOUNT_ID` | https://metaapi.cloud |
| | MT5 REST: broker login, password, server; a VNC user and password | The human's broker account |
| | None: nothing (signals are detected, no orders are placed) | — |
| AI (**required to read signals**) | `DEEPSEEK_API_KEY` or `OPENAI_API_KEY`, or a local Ollama URL | The provider's console |
| Telegram signals (optional) | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` | https://my.telegram.org → API development tools |
| Notifications (optional) | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_NOTIFICATION_CHAT_ID` | @BotFather, @userinfobot |
| Discord signals (optional) | nothing at install time | Set later on the dashboard's Discord page |

Server requirements: Linux x86-64, Docker with the Compose plugin, `git`,
`python3` with `python3-venv` (for the dependency audit), about 4 GB RAM (8 GB
with the MT5 bridge) and 15 GB free disk.

```bash
docker --version && docker compose version && python3 --version
```

## Step 1 — Get the code

```bash
git clone <repository-url> nexal && cd nexal
```

## Step 2 — MT5 bridge first (only for the self-hosted MT5 connection)

Skip this step if the human uses MetaAPI or wants trading off.

The bridge is started **before** the bot: the bot connects to it at startup, and
both must share the same API key.

```bash
docker network inspect mt5-net >/dev/null 2>&1 || docker network create mt5-net

cp mt5/.env.example mt5/.env && chmod 600 mt5/.env
MT5_KEY=$(python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
```

Set these in `mt5/.env` (edit the file; do not echo the values):

| Variable | Value |
|---|---|
| `MT5_API_KEY` | the generated `$MT5_KEY` — keep it for step 3 |
| `CUSTOM_USER`, `PASSWORD` | login for the browser desktop (VNC) |
| `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` | broker account (optional here; can be entered in the terminal instead) |
| `MT5_PERSIST_LOGIN` | `1` if the broker account is set above |

```bash
(cd mt5 && docker compose up -d --build)     # first build downloads several GB
docker logs -f mt5                            # wait for: "MT5 initialized. Starting Flask-SocketIO"
```

If the image build fails, read `mt5/README.md` (section "Security patch image")
before retrying.

**Human step:** the terminal must be logged in to the broker and the
**Algo Trading** button must be ON. The desktop is at `http://127.0.0.1:3001` on
the server; from another machine: `ssh -L 3001:127.0.0.1:3001 <user>@<server>`.

Check:

```bash
curl -s http://127.0.0.1:5002/health          # expect "mt5_connected": true
```

`mt5_connected: false` means the terminal is not logged in yet — that is the
human step above, not an installation error.

## Step 3 — Create `.env`

```bash
cp .env.example .env && chmod 600 .env
```

Fill in (edit the file):

| Variable | Value |
|---|---|
| `SETTINGS_ENCRYPTION_KEY` | **required** — generate: `python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` | **required** — from Clerk |
| `AUTHORIZED_USER_ID` | leave empty for now (step 7) |
| `TRADING_PROVIDER` | `metaapi` or `mt5rest` |
| MetaAPI | `METAAPI_TOKEN`, `METAAPI_ACCOUNT_ID` |
| MT5 REST | `MT5_REST_API_URL=http://mt5:5001`, `MT5_REST_API_KEY=` the `$MT5_KEY` from step 2 |
| No trading yet | `SKIP_METAAPI=true` |
| `PRIMARY_AI_PROVIDER` | `deepseek`, `openai` or `ollama`, plus its key (`DEEPSEEK_API_KEY` / `OPENAI_API_KEY`) or `OLLAMA_URL` |
| Telegram (optional) | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` — leave empty to run without Telegram |
| `DRY_RUN` | `true` for a first install: signals are processed, no orders are sent |

Everything else in `.env.example` has a working default. Remove placeholder
values such as `your_openai_api_key_here` for providers that are not used.

A human can do steps 3–6 interactively instead: `./deploy.sh --init` asks for
these values, writes both env files, starts the MT5 bridge first and then
deploys. As an agent, write the files yourself and run `./deploy.sh`.

## Step 4 — Deploy

```bash
./deploy.sh
```

It runs without prompts when `.env` exists, and does this in order:

1. Creates the Docker networks `traefik-public` and `mt5-net` if they are missing.
2. Dependency audit (`security-audit.sh`). Blocks on known HIGH/CRITICAL
   vulnerabilities. Do not skip it without telling the human
   (`SKIP_SECURITY_AUDIT=1` exists for emergencies).
3. Builds the bot and dashboard images.
4. Preflight checks on the new images.
5. **Database**: `scripts/init_database.sh` inside the bot image. On a first
   install it creates every table from `prisma/schema.prisma`, records the
   shipped migrations as applied, and imports the starting settings from `.env`
   (trading provider, AI provider, risk limits…). On later deploys it backs the
   database up to `backups/` and applies pending migrations.
6. Starts `trading-bot`, `trading-dashboard` and `trading-redis`.
7. Smoke check of the running system.

After the first install the **database is the source of truth** for settings.
Change them in the dashboard; editing `.env` later has no effect on values that
were imported (credentials that only live in `.env` are still read from there).

## Step 5 — Check the result

```bash
docker compose ps                                   # three containers "running"
docker compose logs --tail=80 trading-bot           # look for "Trading Bot is running!"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/sign-in     # expect 200
```

Expected warnings on a fresh install, not errors:

- `Telegram is NOT logged in` or `Telegram is not set up` — done in step 8.
- `Trading DISABLED - Running in SIGNAL DETECTION ONLY mode` — when `SKIP_METAAPI=true`.

A real failure is: a container restarting, `Fatal error` in the bot log, or
`trading provider not healthy` when a trading connection was configured. For the
last one with MT5 REST, re-check step 2 (terminal logged in, same API key in both
env files).

## Step 6 — Reach the dashboard

The dashboard listens on the server's loopback interface only
(`127.0.0.1:3000`, change with `DASHBOARD_PORT`).

- On the server: `http://localhost:3000`
- From another machine: `ssh -L 3000:127.0.0.1:3000 <user>@<server>`, then `http://localhost:3000`
- Public HTTPS: put a reverse proxy in front. With Traefik on the host, set
  `DASHBOARD_DOMAIN` in `.env`; the labels in `docker-compose.yml` do the rest.
  Add that domain to the Clerk application's allowed origins.

Never publish port 3000, 8001, 3001 or 5002 to the internet directly.

## Step 7 — Make the human the owner (human step)

The dashboard accepts exactly one user.

1. The human opens the dashboard and signs up.
2. They copy their user id (`user_…`) from https://dashboard.clerk.com → Users.
3. Put it in `.env` as `AUTHORIZED_USER_ID=user_…`, then:

```bash
docker compose up -d dashboard
```

Until this is done every page answers "Forbidden". That is intended.

## Step 8 — First configuration in the dashboard (human, or agent with the human)

| Where | What |
|---|---|
| Connections | Every card should be OK or deliberately OFF. Log in to Telegram here (code + 2FA). |
| AI & Bot → Telegram | Choose the Telegram channels to listen to. |
| Discord | Optional: bot token or own account, then tick the channels per server. |
| AI & Bot → AI | Add a vision-capable provider key (OpenAI, Gemini…) if signals come as chart images. |
| AI & Bot → Risk | Risk per trade, lot limits, drawdown limits. Check these before any live trade. |
| AI & Bot → Execution | Manual approval and instant execution, per channel if wanted. |
| Simulator / Flow Replay | Replay a channel's recent messages to see what the bot would do, without placing orders. |

Go live only when the human says so: set **Dry Run** off (and
"Disable Trading" off under AI & Bot → System, if it was on), then restart the
bot with `docker compose restart trading-bot`.

## Later: update, back up, roll back

```bash
git pull && ./deploy.sh              # update: builds, backs up the database, migrates, restarts
scripts/rollback.sh                  # return to the previous images
ls backups/                          # database backups made by deploy.sh
docker compose logs -f trading-bot   # live log
```

Back up `.env` and `mt5/.env` separately; without `SETTINGS_ENCRYPTION_KEY` the
secrets stored in the database cannot be read.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Bot log: `SETTINGS_ENCRYPTION_KEY is not set` | Key missing in `.env` | Generate one (step 3). Only on a first install — never replace an existing key. |
| `network mt5-net declared as external, but could not be found` | Network missing | `docker network create mt5-net` (same for `traefik-public`) |
| Dashboard build fails or shows a Clerk error | Clerk keys missing/wrong in `.env` | Fix the keys, `./deploy.sh` again (the publishable key is baked into the build) |
| Every dashboard page says "Forbidden" | `AUTHORIZED_USER_ID` empty or not this user | Step 7 |
| Dashboard pages load but data calls fail with 401 | Bot and dashboard have different `SETTINGS_ENCRYPTION_KEY` | Both read the same `.env`; recreate both: `docker compose up -d --force-recreate` |
| `trading provider not healthy` (MT5 REST) | Terminal not logged in, Algo Trading off, or API keys differ | Step 2 checks; `MT5_API_KEY` in `mt5/.env` must equal `MT5_REST_API_KEY` in `.env` |
| `.env` says `mt5rest` but the bot uses MetaAPI | The database was created before `.env` was filled in | Switch the provider on the dashboard's Connections page |
| Trades show `DRY_RUN_…` instead of a broker ticket | `DRY_RUN` or "Disable Trading" is on | AI & Bot → System, then restart the bot |
| Database tables missing after a manual start | The first start was interrupted | `docker compose run --rm --no-deps --entrypoint sh trading-bot /app/scripts/init_database.sh` |
| Deploy stopped at "Security audit" | A dependency has a known vulnerability | Report it to the human; update the dependency rather than skipping the audit |
