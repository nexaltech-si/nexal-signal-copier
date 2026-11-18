#!/usr/bin/env python3
"""
Query the live bot to see what symbols are in open positions
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.database_service import DatabaseService


async def query_symbols():
    """Query database for symbols in active trades"""
    from src.core.prisma_client import prisma_client
    
    # Initialize Prisma
    await prisma_client.initialize()
    
    db = DatabaseService()
    
    try:
        # Get all active trades
        trades = await db.db.trade.find_many(
            where={
                "status": {"in": ["EXECUTED", "PENDING"]}
            },
            include={
                "signal": True
            }
        )
        
        if trades:
            print(f"\n✅ Found {len(trades)} active trade(s):")
            print("-" * 80)
            
            unique_symbols = set()
            for trade in trades:
                symbol = trade.symbol or (trade.signal.symbol if trade.signal else None)
                unique_symbols.add(symbol)
                
                print(f"Trade ID: {trade.id[:8]}...")
                print(f"  Symbol: {symbol}")
                print(f"  Status: {trade.status}")
                print(f"  Position ID: {trade.positionId}")
                print(f"  Order ID: {trade.orderId}")
                print(f"  Magic: {trade.magicNumber}")
                print()
            
            print("-" * 80)
            print(f"\n📋 Unique symbols: {sorted([s for s in unique_symbols if s])}")
        else:
            print("\n⚠️ No active trades found in database")
        
        # Check signals too
        signals = await db.db.signal.find_many(
            where={
                "status": {"in": ["EXECUTED", "PENDING"]}
            },
            take=10
        )
        
        if signals:
            print(f"\n📊 Recent signals:")
            signal_symbols = set()
            for sig in signals:
                if sig.symbol:
                    signal_symbols.add(sig.symbol)
                    print(f"  - {sig.symbol} ({sig.status})")
            
            print(f"\n📋 Symbols in signals: {sorted(signal_symbols)}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        from src.core.prisma_client import prisma_client
        await prisma_client.disconnect()


if __name__ == "__main__":
    asyncio.run(query_symbols())
