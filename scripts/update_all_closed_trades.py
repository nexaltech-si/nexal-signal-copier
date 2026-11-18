"""
Script to update all closed trades with accurate profit values from trade_lifecycle API
This will correct any discrepancies in the database profit values
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.integrations.trading.provider_factory import create_trading_provider
from src.core.prisma_client import prisma_client
from loguru import logger


async def update_all_closed_trades(days_back: int = 30):
    """
    Update all closed trades within the specified time range with accurate profit values
    
    Args:
        days_back: Number of days to look back for closed trades (default: 30)
    """
    
    print("=" * 80)
    print("UPDATING ALL CLOSED TRADES WITH ACCURATE PROFIT VALUES")
    print("=" * 80)
    print()
    
    try:
        # Connect to database
        print("🔌 Connecting to database...")
        await prisma_client.ensure_connected()
        print("✅ Database connected")
        print()
        
        # Create trading provider
        print("🔌 Creating trading provider...")
        provider = create_trading_provider()
        print(f"✅ Provider created: {type(provider).__name__}")
        print()
        
        # Check if provider supports trade_lifecycle
        if not hasattr(provider, 'get_trade_lifecycle'):
            print("❌ Provider does not support get_trade_lifecycle method")
            print("   This feature is only available for MT5REST provider")
            return
        
        # Initialize provider
        print("🔌 Initializing provider...")
        await provider.initialize()
        print("✅ Provider initialized")
        print()
        
        # Query closed trades from database
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        print(f"📊 Fetching closed trades since {cutoff_date.date()}...")
        
        closed_trades = await prisma_client.client.trade.find_many(
            where={
                "status": "CLOSED",
                "closedAt": {"gte": cutoff_date}
            },
            order={"closedAt": "desc"}
        )
        
        if not closed_trades:
            print("❌ No closed trades found in the specified time range")
            return
        
        print(f"✅ Found {len(closed_trades)} closed trade(s)")
        print()
        
        # Process each trade
        updated_count = 0
        skipped_count = 0
        error_count = 0
        
        for trade in closed_trades:
            trade_id = trade.id[:8] + "..."
            position_id = trade.positionId
            current_profit = trade.profitLoss
            
            print(f"Processing trade {trade_id} (position: {position_id[:8] if position_id else 'N/A'}...)")
            profit_display = current_profit if current_profit is not None else 0
            print(f"  Current profit: ${profit_display:.2f}")
            
            if not position_id:
                print(f"  ⏭️ Skipping - no position ID")
                skipped_count += 1
                print()
                continue
            
            # Fetch trade lifecycle
            try:
                lifecycle_data = await provider.get_trade_lifecycle(position_id, days_back=30)
                
                if not lifecycle_data:
                    print(f"  ⚠️ No lifecycle data available")
                    error_count += 1
                    print()
                    continue
                
                summary = lifecycle_data.get('summary', {})
                lifecycle_profit = summary.get('net_pnl')
                
                if lifecycle_profit is None:
                    print(f"  ⚠️ No profit data in lifecycle")
                    error_count += 1
                    print()
                    continue
                
                lifecycle_profit = float(lifecycle_profit)
                
                # Check if profit needs updating
                if current_profit is None or abs(lifecycle_profit - current_profit) > 0.01:
                    current_display = current_profit if current_profit is not None else 0
                    print(f"  📊 Updating profit: ${current_display:.2f} → ${lifecycle_profit:.2f}")
                    
                    # Update trade with accurate values
                    update_data = {
                        "profitLoss": lifecycle_profit,
                        "closePrice": summary.get('exit_price'),
                        "lastModifiedAt": datetime.now(timezone.utc)
                    }
                    
                    await prisma_client.client.trade.update(
                        where={"id": trade.id},
                        data=update_data
                    )
                    
                    updated_count += 1
                    print(f"  ✅ Trade updated")
                else:
                    print(f"  ✅ Profit already accurate (${lifecycle_profit:.2f})")
                    skipped_count += 1
                
                print()
                
            except Exception as e:
                print(f"  ❌ Error processing trade: {str(e)}")
                error_count += 1
                print()
        
        # Summary
        print("=" * 80)
        print("UPDATE SUMMARY")
        print("=" * 80)
        print(f"Total trades processed: {len(closed_trades)}")
        print(f"Updated: {updated_count}")
        print(f"Skipped (already accurate): {skipped_count}")
        print(f"Errors: {error_count}")
        print("=" * 80)
        print()
        
        if updated_count > 0:
            print(f"✅ Successfully updated {updated_count} trade(s) with accurate profit values")
        else:
            print("ℹ️  All trades already have accurate profit values")
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        logger.exception(e)
    finally:
        if 'provider' in locals():
            await provider.disconnect()
        await prisma_client.disconnect()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Update closed trades with accurate profit values")
    parser.add_argument(
        "--days-back",
        type=int,
        default=30,
        help="Number of days to look back for closed trades (default: 30)"
    )
    
    args = parser.parse_args()
    asyncio.run(update_all_closed_trades(days_back=args.days_back))
