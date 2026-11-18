#!/usr/bin/env python3
"""
Vision AI test script — loads all config from the database and runs
ImageSignalExtractor against a provided chart image.

Uses the same vision provider / model as the dashboard config
(reads provider and gemini_vision_model from DB settings).

Usage:
    python scripts/test_vision.py <image_path> [--message "optional caption"]
    python scripts/test_vision.py /tmp/chart.png
    python scripts/test_vision.py /tmp/chart.png --message "SELL NAS100"
"""

import sys
import os
import asyncio
import argparse
import json
import base64
import sqlite3
import logging

# ── project root on path ─────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── import bootstrap ─────────────────────────────────────────────────────────
# src/__init__.py imports the full trading stack (services, telegram, etc.)
# which causes circular imports in standalone scripts.  We stub `src` in
# sys.modules so that `from src.models import …` resolves to the pure-data
# models package without running src/__init__.py at all.
def _bootstrap_trading_imports():
    import types, importlib

    if "src" not in sys.modules or not hasattr(sys.modules["src"], "_bootstrapped"):
        src_pkg = types.ModuleType("src")
        src_pkg.__path__ = [os.path.join(ROOT, "src")]
        src_pkg.__package__ = "src"
        src_pkg._bootstrapped = True
        sys.modules["src"] = src_pkg

    # Ensure src.models sub-package is importable
    import importlib.util as _ilu
    if "src.models" not in sys.modules:
        _spec = _ilu.spec_from_file_location(
            "src.models",
            os.path.join(ROOT, "src", "models", "__init__.py"),
            submodule_search_locations=[os.path.join(ROOT, "src", "models")],
        )
        _mod = _ilu.module_from_spec(_spec)
        sys.modules["src.models"] = _mod
        _spec.loader.exec_module(_mod)
        sys.modules["src"].models = _mod

    # Stub the ai package (avoids ai/__init__.py which also chains the stack)
    if "ai" not in sys.modules or not hasattr(sys.modules["ai"], "_bootstrapped"):
        ai_pkg = types.ModuleType("ai")
        ai_pkg.__path__ = [os.path.join(ROOT, "ai")]
        ai_pkg.__package__ = "ai"
        ai_pkg._bootstrapped = True
        sys.modules["ai"] = ai_pkg


# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s  %(name)s  %(message)s",
)
logger = logging.getLogger("test_vision")


# ── decryption (mirrors SettingsService._decrypt) ────────────────────────────
def _make_fernet(encryption_key: str):
    from cryptography.fernet import Fernet
    try:
        return Fernet(encryption_key.encode())
    except Exception:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32,
            salt=b"trading-bot-salt", iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(encryption_key.encode()))
        return Fernet(key)


def decrypt_value(fernet, value: str) -> str:
    if not value:
        return value
    try:
        raw = base64.urlsafe_b64decode(value.encode())
        return fernet.decrypt(raw).decode()
    except Exception:
        pass
    try:
        return fernet.decrypt(value.encode()).decode()
    except Exception:
        pass
    return value  # plain text — return as-is


# ── DB settings loader ────────────────────────────────────────────────────────
ENCRYPTED_KEYS = {
    "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY",
    "PERPLEXITY_API_KEY", "MINIMAX_API_KEY", "QWEN_API_KEY",
    "TELEGRAM_BOT_TOKEN", "METAAPI_TOKEN", "MT5_REST_API_KEY",
    "SIGNAL_VALIDATOR_API_KEY", "DASHBOARD_HASHED_PASSWORD", "BRAIN_API_KEY",
}

KEY_MAPPING = {
    "OPENAI_API_KEY":               "openai_api_key",
    "OPENAI_MODEL":                 "openai_model",
    "OPENAI_VISION_MODEL":          "openai_vision_model",
    "GEMINI_API_KEY":               "gemini_api_key",
    "GEMINI_MODEL":                 "gemini_model",
    "GEMINI_VISION_MODEL":          "gemini_vision_model",
    "DEEPSEEK_API_KEY":             "deepseek_api_key",
    "DEEPSEEK_API_URL":             "deepseek_api_url",
    "DEEPSEEK_MODEL":               "deepseek_model",
    "DEEPSEEK_VISION_MODEL":        "deepseek_vision_model",
    "PERPLEXITY_API_KEY":           "perplexity_api_key",
    "PERPLEXITY_BASE_URL":          "perplexity_base_url",
    "PERPLEXITY_MODEL":             "perplexity_model",
    "PERPLEXITY_VISION_MODEL":      "perplexity_vision_model",
    "OPENROUTER_API_KEY":           "openrouter_api_key",
    "OPENROUTER_BASE_URL":          "openrouter_base_url",
    "OPENROUTER_MODEL":             "openrouter_model",
    "OPENROUTER_VISION_MODEL":      "openrouter_vision_model",
    "MINIMAX_API_KEY":              "minimax_api_key",
    "MINIMAX_BASE_URL":             "minimax_base_url",
    "MINIMAX_MODEL":                "minimax_model",
    "MINIMAX_VISION_MODEL":         "minimax_vision_model",
    "QWEN_API_KEY":                 "qwen_api_key",
    "QWEN_BASE_URL":                "qwen_base_url",
    "QWEN_MODEL":                   "qwen_model",
    "QWEN_VISION_MODEL":            "qwen_vision_model",
    "OLLAMA_URL":                   "ollama_url",
    "OLLAMA_MODEL":                 "ollama_model",
    "PRIMARY_AI_PROVIDER":          "primary_ai_provider",
    "FALLBACK_AI_PROVIDERS":        "fallback_ai_providers",
    "provider":                     "provider",
    "ENABLE_AI_VISION":             "enable_ai_vision",
    "VISION_CAPTION_PREFILTER_ENABLED":    "vision_caption_prefilter_enabled",
    "VISION_CAPTION_BLOCK_KEYWORDS":       "vision_caption_block_keywords",
    "VISION_CONFIDENCE_FILTER_ENABLED":    "vision_confidence_filter_enabled",
    "VISION_MIN_CONFIDENCE":               "vision_min_confidence",
    "VISION_TWO_STEP_CLASSIFY_ENABLED":    "vision_two_step_classify_enabled",
    "VISION_PRICE_SANITY_CHECK_ENABLED":   "vision_price_sanity_check_enabled",
    "VISION_PRICE_RANGES":                 "vision_price_ranges",
    "VISION_SL_DISTANCE_CHECK_ENABLED":    "vision_sl_distance_check_enabled",
    "VISION_MAX_SL_DISTANCE_PERCENT":      "vision_max_sl_distance_percent",
    "VISION_SYMBOL_WHITELIST_ENABLED":     "vision_symbol_whitelist_enabled",
    "VISION_ALLOWED_SYMBOLS":              "vision_allowed_symbols",
    "VISION_IMAGE_DIMENSION_FILTER_ENABLED": "vision_image_dimension_filter_enabled",
    "VISION_MAX_IMAGE_ASPECT_RATIO":       "vision_max_image_aspect_ratio",
    "VISION_MIN_IMAGE_HEIGHT":             "vision_min_image_height",
}

TYPE_CAST = {
    "FLOAT":  float,
    "INT":    int,
    "BOOL":   lambda v: str(v).lower() in ("true", "1", "yes"),
    "JSON":   str,   # keep as string; Settings-level code parses it
    "STRING": str,
}


def load_config_from_db(db_path: str, encryption_key: str) -> dict:
    fernet = _make_fernet(encryption_key)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT key, value, valueType, isSecret FROM settings")
    rows = cur.fetchall()
    conn.close()

    raw: dict = {}
    for row in rows:
        key, value, vtype, is_secret = row["key"], row["value"], row["valueType"], row["isSecret"]
        if is_secret or key in ENCRYPTED_KEYS:
            value = decrypt_value(fernet, value)
        caster = TYPE_CAST.get(vtype, str)
        try:
            raw[key] = caster(value)
        except Exception:
            raw[key] = value

    return raw


class SimpleConfig:
    """Lightweight stand-in for Settings — just holds attributes."""
    pass


def build_config(raw: dict) -> SimpleConfig:
    cfg = SimpleConfig()
    for db_key, attr in KEY_MAPPING.items():
        if db_key in raw:
            setattr(cfg, attr, raw[db_key])

    # Resolve fallback_providers into a list (mirrors the Settings property)
    fb = getattr(cfg, "fallback_ai_providers", "")
    if isinstance(fb, str):
        fb = fb.strip().strip('"')
        if fb.startswith("["):
            try:
                parsed = json.loads(fb)
                cfg.fallback_providers = [str(p).strip() for p in parsed]
            except Exception:
                cfg.fallback_providers = [p.strip() for p in fb.strip("[]").split(",") if p.strip()]
        else:
            cfg.fallback_providers = [p.strip() for p in fb.split(",") if p.strip()]
    else:
        cfg.fallback_providers = []

    # vision_provider alias used by provider_chain()
    if not hasattr(cfg, "vision_provider"):
        cfg.vision_provider = getattr(cfg, "provider", "gemini")

    # default temperature for extractor
    if not hasattr(cfg, "temperature"):
        cfg.temperature = 0.1

    return cfg


# ── Gemini API ping — validates key + model before the full test ──────────────
def gemini_ping(api_key: str, model: str) -> tuple[bool, str]:
    """
    Makes a minimal vision call to Gemini to confirm the key and model work.
    Returns (ok: bool, message: str).
    """
    try:
        from openai import OpenAI, NotFoundError, AuthenticationError, BadRequestError
        client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        # Tiny 1×1 red PNG so we're not sending real data
        tiny_png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
            "z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
        )
        client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image in one word."},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{tiny_png_b64}"
                    }},
                ],
            }],
            max_tokens=5,
        )
        return True, "API key and model are valid."
    except NotFoundError as e:
        return False, f"Model not found: {e}"
    except AuthenticationError as e:
        return False, f"API key invalid: {e}"
    except BadRequestError as e:
        return False, f"Bad request (model may not support vision): {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"


# ── main ──────────────────────────────────────────────────────────────────────
async def run(image_path: str, message: str):
    db_path = os.path.join(ROOT, "data", "trading_bot.db")
    enc_key = os.environ.get(
        "SETTINGS_ENCRYPTION_KEY",
        "hIsCjTNcSeBKdzyyz7KsJx6hQ1RUNxlP9hYBrpZfLgI="
    )

    sep = "=" * 62
    print(f"\n{sep}\n  VISION AI DIAGNOSTIC TEST\n{sep}")

    # ── Step 1: load DB config ────────────────────────────────────────────────
    print(f"\n[1/5] Loading config from DB …")
    raw  = load_config_from_db(db_path, enc_key)
    cfg  = build_config(raw)

    vision_provider = getattr(cfg, "vision_provider", "gemini")
    vision_model    = getattr(cfg, "gemini_vision_model", "gemini-2.5-flash")
    gemini_key      = getattr(cfg, "gemini_api_key", None)

    print(f"      vision_provider      : {vision_provider}")
    print(f"      gemini_vision_model  : {vision_model}")
    print(f"      enable_ai_vision     : {getattr(cfg, 'enable_ai_vision', True)}")
    print(f"      min_confidence       : {getattr(cfg, 'vision_min_confidence', 0.75)}")
    print(f"      two_step_classify    : {getattr(cfg, 'vision_two_step_classify_enabled', True)}")
    print(f"      fallback_providers   : {getattr(cfg, 'fallback_providers', [])}")
    if gemini_key:
        print(f"      gemini_api_key       : {'*'*8}{gemini_key[-6:]}")
    else:
        print(f"      gemini_api_key       : ⚠️  NOT SET")

    # ── Step 2: Gemini API ping ───────────────────────────────────────────────
    print(f"\n[2/5] Pinging Gemini API with model '{vision_model}' …")
    if gemini_key:
        ok, msg = gemini_ping(gemini_key, vision_model)
        status = "✅" if ok else "❌"
        print(f"      {status}  {msg}")
        if not ok:
            # Try known-good model to isolate the issue
            fallback_model = "gemini-2.5-flash"
            print(f"\n      Retrying with fallback model '{fallback_model}' …")
            ok2, msg2 = gemini_ping(gemini_key, fallback_model)
            status2 = "✅" if ok2 else "❌"
            print(f"      {status2}  {msg2}")
            if ok2:
                print(f"\n      ⚠️  ROOT CAUSE: model '{vision_model}' does not exist on Gemini.")
                print(f"         Fix: set GEMINI_VISION_MODEL to '{fallback_model}'")
    else:
        print("      ⚠️  No Gemini API key — skipping ping")

    # ── Step 3: read image ────────────────────────────────────────────────────
    print(f"\n[3/5] Reading image: {image_path}")
    with open(image_path, "rb") as f:
        image_data = f.read()
    print(f"      Size: {len(image_data):,} bytes")

    # ── Step 4: dimension pre-check ───────────────────────────────────────────
    print(f"\n[4/5] Dimension pre-filter …")
    _bootstrap_trading_imports()
    from ai.image_signal_extractor import ImageSignalExtractor
    extractor = ImageSignalExtractor(cfg)
    is_deco, reason = extractor.is_probably_decorative(image_data)
    if is_deco:
        print(f"      ⚠️  Flagged as decorative: {reason}  (continuing for test)")
    else:
        print(f"      ✅ Passed")

    # ── Step 5: full vision extraction ───────────────────────────────────────
    print(f"\n[5/5] Running vision extraction …")
    print(f"      message caption: '{message}'")
    print()

    signals = await extractor.process_message_with_image(
        message_text=message,
        image_data=image_data,
    )

    print(f"\n{sep}")
    if not signals:
        rejection = getattr(extractor, "last_rejection_reason", None)
        print(f"  RESULT: No signals extracted")
        if rejection:
            print(f"  Rejection reason: {rejection}")
        else:
            print(f"  (check DEBUG output above for the classify/filter step that dropped it)")
    else:
        print(f"  RESULT: {len(signals)} signal(s) extracted")
        for i, sig in enumerate(signals, 1):
            print(f"\n  Signal #{i}:")
            print(f"    Symbol      : {sig.symbol}")
            print(f"    Action      : {sig.action}")
            print(f"    Order type  : {sig.order_type}")
            print(f"    Signal type : {sig.signal_type}")
            print(f"    Entry price : {sig.entry_price}")
            print(f"    Stop loss   : {sig.stop_loss}")
            print(f"    Take profit : {sig.take_profit}")
            print(f"    Is plan     : {sig.is_plan}")
            print(f"    Confidence  : {sig.confidence}")
            if sig.plan_data:
                print(f"    Plan data   : {json.dumps(sig.plan_data, indent=6)}")
    print(f"{sep}\n")


def main():
    parser = argparse.ArgumentParser(description="Test vision AI with a chart image")
    parser.add_argument("image", help="Path to the chart image (PNG/JPG)")
    parser.add_argument("--message", default="", help="Optional message caption (e.g. 'SELL NAS100')")
    args = parser.parse_args()

    if not os.path.isfile(args.image):
        print(f"Error: image not found: {args.image}")
        sys.exit(1)

    asyncio.run(run(args.image, args.message))


if __name__ == "__main__":
    main()
