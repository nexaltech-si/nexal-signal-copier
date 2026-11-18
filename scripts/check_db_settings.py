#!/usr/bin/env python3
"""Quick script to check database settings"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.prisma_client import prisma_client


async def main():
    await prisma_client.initialize()
    db = prisma_client.client
    
    # Count total settings
    total = await db.setting.count()
    print(f"Total settings in database: {total}")
    
    # Check critical API keys
    critical_keys = [
        'METAAPI_TOKEN',
        'MT5_REST_API_KEY',
        'OPENAI_API_KEY',
        'TELEGRAM_BOT_TOKEN',
        'BREAKEVEN_MIN_SIBLING_TP_HITS'
    ]
    
    print("\nAPI Keys in database:")
    for key in critical_keys:
        setting = await db.setting.find_unique(where={'key': key})
        if setting:
            is_empty = setting.value == "" or setting.value == "encrypted_"
            status = "✅ SET" if not is_empty else "⚠️  EMPTY"
            print(f"  {key}: {status} (encrypted: {setting.isSecret})")
        else:
            print(f"  {key}: ❌ NOT IN DATABASE")
    
    await prisma_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
