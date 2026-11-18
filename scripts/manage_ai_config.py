#!/usr/bin/env python3
"""
AI Configuration Management Script
View and update position sizing settings in the database.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.database_service import db_service
from loguru import logger


async def view_config():
    """View current AI configuration"""
    try:
        config = await db_service.db.aiconfiguration.find_first()

        if not config:
            print("❌ No AI configuration found in database")
            return

        print("\n" + "="*50)
        print("🤖 AI CONFIGURATION")
        print("="*50 + "\n")

        print("💰 POSITION SIZING:")
        print(f"   Enabled:               {'✅ YES' if config.enablePositionSizing else '❌ NO'}")
        print(f"   Base Risk Percent:     {config.baseRiskPercent}%")
        print(f"   Min Lot Size:          {config.minLotSize}")
        print(f"   Max Lot Size:          {config.maxLotSize}")
        print(f"   Volatility Multiplier: {config.volatilityMultiplier}")

        print("\n" + "="*50 + "\n")

    except Exception as e:
        print(f"❌ Error viewing config: {e}")
        logger.exception(e)


async def update_config(updates: dict):
    """Update AI configuration"""
    try:
        config = await db_service.db.aiconfiguration.find_first()

        if not config:
            print("❌ No AI configuration found")
            return

        await db_service.db.aiconfiguration.update(
            where={'id': config.id},
            data=updates
        )

        print("✅ Configuration updated successfully!")
        for key, value in updates.items():
            print(f"   {key}: {value}")

    except Exception as e:
        print(f"❌ Error updating config: {e}")
        logger.exception(e)


async def set_position_sizing(enable: bool = None, base_risk: float = None,
                               min_lot: float = None, max_lot: float = None,
                               volatility: float = None):
    """Set position sizing parameters"""
    updates = {}
    if enable is not None:
        updates['enablePositionSizing'] = enable
    if base_risk is not None:
        updates['baseRiskPercent'] = base_risk
    if min_lot is not None:
        updates['minLotSize'] = min_lot
    if max_lot is not None:
        updates['maxLotSize'] = max_lot
    if volatility is not None:
        updates['volatilityMultiplier'] = volatility

    if updates:
        await update_config(updates)


async def interactive_menu():
    """Interactive configuration menu"""
    while True:
        print("\n" + "="*50)
        print("🤖 AI CONFIGURATION MANAGER")
        print("="*50)
        print("\n1. View current configuration")
        print("2. Set position sizing")
        print("0. Exit")

        choice = input("\nEnter choice: ").strip()

        if choice == '0':
            print("👋 Goodbye!")
            break

        elif choice == '1':
            await view_config()

        elif choice == '2':
            enable = input("Enable position sizing? (y/n, Enter to skip): ").strip()
            base_risk = input("Base risk % (Enter to skip): ").strip()
            min_lot = input("Min lot size (Enter to skip): ").strip()
            max_lot = input("Max lot size (Enter to skip): ").strip()
            volatility = input("Volatility multiplier (Enter to skip): ").strip()
            await set_position_sizing(
                enable=(True if enable == 'y' else False if enable == 'n' else None),
                base_risk=float(base_risk) if base_risk else None,
                min_lot=float(min_lot) if min_lot else None,
                max_lot=float(max_lot) if max_lot else None,
                volatility=float(volatility) if volatility else None,
            )


async def main():
    """Main function"""
    try:
        from src.core.prisma_client import prisma_client
        await prisma_client.ensure_connected()

        config = await db_service.db.aiconfiguration.find_first()
        if not config:
            print("⚠️  No AI configuration found. Creating default...")
            config = await db_service.db.aiconfiguration.create(data={})
            print("✅ Default configuration created")

        if len(sys.argv) > 1:
            command = sys.argv[1].lower()

            if command == 'view':
                await view_config()
            elif command == 'interactive':
                await interactive_menu()
            else:
                print("Usage:")
                print("  python3 manage_ai_config.py view")
                print("  python3 manage_ai_config.py interactive")
        else:
            await view_config()

        await prisma_client.disconnect()

    except Exception as e:
        print(f"❌ Error: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
