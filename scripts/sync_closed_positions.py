"""
Manually trigger position monitor to sync closed positions
This will update the database with corrected profit values
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.position_monitor_service import PositionMonitorService
from src.integrations.metaapi import metaapi_trader
from src.core.prisma_client import prisma_client
from loguru import logger


async def sync_closed_positions():
    """Manually sync closed positions"""
    
    print("=" * 80)
    print("SYNCING CLOSED POSITIONS")
    print("=" * 80)
    print()
    
    try:
        # Connect to database
        print("🔌 Connecting to database...")
        await prisma_client.ensure_connected()
        print("✅ Database connected")
        print()
        
        # Connect to MetaAPI
        print("🔌 Connecting to MetaAPI...")
        await metaapi_trader.initialize()
        print("✅ MetaAPI connected")
        print()
        
        # Create position monitor instance
        monitor = PositionMonitorService()
        
        # Get all open positions from MetaAPI
        print("📊 Fetching open positions from MetaAPI...")
        open_positions = await metaapi_trader.get_open_positions()
        print(f"✅ Found {len(open_positions)} open position(s)")
        print()
        
        # Manually trigger the closed position check
        print("🔄 Checking for closed positions...")
        print("   (This will update database with corrected profit values)")
        print()
        
        await monitor._check_for_closed_positions(open_positions)
        
        print()
        print("✅ Sync complete!")
        print()
        print("Now run the test script again to see corrected values:")
        print("  python3 scripts/test_todays_trades.py")
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        logger.exception(e)
    finally:
        await metaapi_trader.disconnect()
        await prisma_client.disconnect()


if __name__ == "__main__":
    asyncio.run(sync_closed_positions())
