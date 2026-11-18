"""
Standalone CLI for the Trading Simulator.

Used when the live bot is NOT running (own Telegram session).
Telegram credentials come from .env (needed to open a session at all); every
AI/pipeline setting (provider, vision_provider, models, fallbacks) is loaded
from the SAME database the live bot reads — never re-derived from .env — so
the CLI run always matches whatever is configured in the dashboard.

Usage:
  python -m simulator.cli
  python -m simulator.cli --days 7 --limit 500
  python -m simulator.cli --mode batch --days 30 --limit 1000
  python -m simulator.cli --brain
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _banner() -> None:
    print("\n" + "=" * 76)
    print("  TRADING SIGNAL SIMULATOR — Full Live-System Pipeline")
    print("  Intent → Pre-filter → AI/Vision/Pattern → Context → Brain")
    print("=" * 76 + "\n")


async def _fetch_channels(client) -> List[dict]:
    """Fetch all channels and supergroups from Telegram dialogs."""
    from telethon.tl.types import Channel
    channels = []
    print("Fetching your Telegram channels…")
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, Channel):
            channels.append({
                "id": entity.id,
                "name": dialog.name or entity.username or str(entity.id),
                "type": "channel" if entity.broadcast else "group",
            })
    channels.sort(key=lambda c: c["name"].lower())
    return channels


def _pick_channel(channels: List[dict]) -> dict:
    print(f"\n{'─'*60}")
    for i, ch in enumerate(channels, 1):
        tag = "CH" if ch["type"] == "channel" else "GR"
        print(f"  {i:3}. [{tag}] {ch['name']}  (id={ch['id']})")
    print(f"{'─'*60}")
    while True:
        raw = input("Select channel number [q to quit]: ").strip()
        if raw.lower() == "q":
            sys.exit(0)
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(channels):
                return channels[idx]
        except ValueError:
            pass
        print(f"Enter 1–{len(channels)}")


def _pick_date_range(days_back: int) -> tuple[datetime, datetime]:
    now = datetime.now()
    if days_back:
        return now - timedelta(days=days_back), now

    print(f"\nDate range  (today: {now.strftime('%Y-%m-%d')})")
    print("  1. Last 7 days")
    print("  2. Last 30 days")
    print("  3. Last 90 days")
    print("  4. Custom range")
    print("  5. All available")
    while True:
        choice = input("Choice [1-5]: ").strip()
        if choice == "1":
            return now - timedelta(days=7), now
        if choice == "2":
            return now - timedelta(days=30), now
        if choice == "3":
            return now - timedelta(days=90), now
        if choice == "4":
            try:
                start = datetime.strptime(input("Start (YYYY-MM-DD): "), "%Y-%m-%d")
                end = datetime.strptime(input("End   (YYYY-MM-DD): "), "%Y-%m-%d")
                return start, end
            except ValueError as exc:
                print(f"Invalid date: {exc}")
        if choice == "5":
            return datetime(2020, 1, 1), now


async def _load_db_backed_ai_config():
    """
    Connect to the SAME database the live bot uses and return its database-
    backed AI config (signal_service.ai_config) — provider, vision_provider,
    models, fallbacks, vision filters, all loaded from DB, never from raw
    .env parsing. Mirrors main.py's TradingBot.initialize() DB-settings step.
    """
    from src.core.prisma_client import prisma_client
    from src.services.settings_service import get_settings_service
    from config import settings as live_settings

    await prisma_client.initialize()

    encryption_key = os.getenv("SETTINGS_ENCRYPTION_KEY")
    settings_service = await get_settings_service(prisma_client.client, encryption_key=encryption_key)
    live_settings.set_db_settings_service(settings_service)
    await live_settings.reload_from_db()

    from src.services.signal_service import signal_service
    signal_service.reinitialize()
    return signal_service.ai_config


async def _disconnect_db() -> None:
    """Best-effort Prisma disconnect on CLI exit (mirrors main.py shutdown)."""
    try:
        from src.core.prisma_client import prisma_client
        await prisma_client.disconnect()
    except Exception:
        pass


async def _build_engine(enable_brain: bool):
    """Create and connect a standalone TradingSimulator with its own Telegram session."""
    from simulator.engine import TradingSimulator

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE")

    if not all([api_id, api_hash, phone]):
        print("Missing credentials. Set TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE in .env")
        sys.exit(1)

    print("Loading AI config from database…")
    ai_config = await _load_db_backed_ai_config()

    engine = TradingSimulator(
        api_id=int(api_id),
        api_hash=api_hash,
        phone=phone,
        session_name="simulator_session",
        enable_brain=enable_brain,
    )
    await engine.initialize(ai_config)
    return engine


async def _run_interactive(args) -> None:
    _banner()
    engine = await _build_engine(args.brain)
    try:
        channels = await _fetch_channels(engine.client)
        if not channels:
            print("No channels found.")
            return

        channel = _pick_channel(channels)
        start_date, end_date = _pick_date_range(args.days)
        limit = args.limit or _ask_limit()
        enable_brain = args.brain or _ask_brain()
        engine.enable_brain = enable_brain

        print(f"\n{'='*76}")
        print(f"  Channel : {channel['name']}")
        print(f"  Period  : {start_date.date()} → {end_date.date()}")
        print(f"  Limit   : {limit}")
        print(f"  Brain   : {'YES' if enable_brain else 'no'}")
        print(f"{'='*76}")
        if input("Start? [y/N]: ").strip().lower() != "y":
            return

        async def _progress(current: int, total: int, trade) -> None:
            symbol = trade.ai_symbol or trade.pattern_symbol or "?"
            action = trade.ai_action or trade.pattern_action or trade.command_action or trade.extraction_method
            print(f"  [{current:4d}/{total}] {trade.timestamp.strftime('%m-%d %H:%M')}  "
                  f"{trade.intent or '?':10}  {action or '?':12}  {symbol}")

        results = await engine.run(
            channel_id=channel["id"],
            channel_name=channel["name"],
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            on_progress=_progress,
        )
        _print_summary(results)
    finally:
        await engine.close()
        await _disconnect_db()


async def _run_batch(args) -> None:
    _banner()
    print("BATCH MODE — all broadcast channels\n")
    engine = await _build_engine(args.brain)
    try:
        all_dialogs = await _fetch_channels(engine.client)
        channels = [c for c in all_dialogs if c["type"] == "channel"]
        if not channels:
            print("No broadcast channels found.")
            return

        days = args.days or 30
        limit = args.limit or 1000
        now = datetime.now()
        print(f"{len(channels)} channels — last {days} days, up to {limit} msgs each\n")

        for i, ch in enumerate(channels, 1):
            print(f"[{i}/{len(channels)}] {ch['name']}")
            try:
                results = await engine.run(
                    channel_id=ch["id"],
                    channel_name=ch["name"],
                    start_date=now - timedelta(days=days),
                    end_date=now,
                    limit=limit,
                )
                extracted = results.ai_extracted_count + results.pattern_extracted_count
                print(f"  ✓ {results.total_messages} msgs, {extracted} extracted")
            except Exception as exc:
                print(f"  ✗ {exc}")

        print("\nBatch complete. Results in simulator/results/")
    finally:
        await engine.close()
        await _disconnect_db()


def _ask_limit() -> int:
    raw = input("\nMessage limit [1000]: ").strip()
    return int(raw) if raw.isdigit() else 1000


def _ask_brain() -> bool:
    return input("Enable TradingBrain review? [y/N]: ").strip().lower() == "y"


def _print_summary(results) -> None:
    print(f"\n{'='*76}")
    print("  SIMULATION RESULTS")
    print(f"{'='*76}")
    print(f"  Messages     : {results.total_messages}")
    print(f"  Signals      : {results.intent_signal_count}")
    print(f"  Commands     : {results.intent_command_count}")
    print(f"  Status/Other : {results.intent_status_count + results.intent_non_trading_count}")
    print(f"\n  AI extracted     : {results.ai_extracted_count} ({results.ai_accuracy:.1f}%)")
    print(f"  Pattern matched  : {results.pattern_extracted_count} ({results.pattern_accuracy:.1f}%)")
    print(f"  Image vision     : {results.image_extracted_count}")
    print(f"  Fused            : {results.fused_extracted_count}")
    print(f"  Pre-filtered     : {results.prefiltered_count}")
    print(f"  Failed           : {results.failed_extraction_count}")
    print(f"\n  OPEN/CLOSE/MODIFY: {results.open_signals} / {results.close_signals} / {results.modify_signals}")
    if results.symbol_distribution:
        top = sorted(results.symbol_distribution.items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"\n  Top symbols: {', '.join(f'{s}:{n}' for s, n in top)}")
    if results.brain_reviewed_count:
        print(f"\n  Brain: {results.brain_reviewed_count} reviewed "
              f"({results.brain_approved} approved / {results.brain_rejected} rejected)")
    print(f"\n  Results saved to simulator/results/")
    print("=" * 76 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trading Signal Simulator")
    parser.add_argument("--mode", choices=["interactive", "batch"], default="interactive")
    parser.add_argument("--days", type=int, default=0, help="Days back (0 = prompt)")
    parser.add_argument("--limit", type=int, default=0, help="Message limit (0 = prompt)")
    parser.add_argument("--brain", action="store_true", default=False)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    if args.mode == "interactive":
        asyncio.run(_run_interactive(args))
    else:
        asyncio.run(_run_batch(args))


if __name__ == "__main__":
    main()
