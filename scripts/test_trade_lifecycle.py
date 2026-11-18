"""
Test script to verify trade_lifecycle API integration
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.integrations.trading.provider_factory import create_trading_provider
from loguru import logger


async def test_trade_lifecycle():
    """Test the trade_lifecycle API integration"""
    
    print("=" * 80)
    print("TESTING TRADE LIFECYCLE API")
    print("=" * 80)
    print()
    
    try:
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
        
        # Test with the provided ticket
        ticket = "8512845305"
        print(f"📊 Fetching trade lifecycle for ticket {ticket}...")
        lifecycle_data = await provider.get_trade_lifecycle(ticket, days_back=30)
        
        if not lifecycle_data:
            print("❌ No data returned from trade_lifecycle API")
            return
        
        print("✅ Trade lifecycle data received")
        print()
        
        # Display the data
        print("TRADE LIFECYCLE DATA:")
        print("-" * 80)
        
        # Display summary
        summary = lifecycle_data.get('summary', {})
        print(f"Status: {lifecycle_data.get('status')}")
        print(f"Net PnL: ${summary.get('net_pnl', 0):.2f}")
        print(f"Entry Price: {summary.get('entry_price')}")
        print(f"Exit Price: {summary.get('exit_price')}")
        print(f"Entry Time: {summary.get('entry_time')}")
        print(f"Exit Time: {summary.get('exit_time')}")
        print()
        
        # Display deals
        deals = lifecycle_data.get('deals', [])
        print(f"Total Deals: {len(deals)}")
        for i, deal in enumerate(deals):
            print(f"  Deal {i+1}:")
            print(f"    Type: {deal.get('type')}")
            print(f"    Entry: {deal.get('entry')}")
            print(f"    Price: {deal.get('price')}")
            print(f"    Volume: {deal.get('volume')}")
            print(f"    Profit: ${deal.get('profit', 0):.2f}")
            print(f"    Time: {deal.get('time')}")
        print()
        
        # Verify the profit matches the expected value
        expected_profit = 290.74
        actual_profit = summary.get('net_pnl')
        
        if actual_profit is not None:
            print(f"PROFIT VERIFICATION:")
            print(f"  Expected: ${expected_profit:.2f}")
            print(f"  Actual: ${actual_profit:.2f}")
            
            if abs(actual_profit - expected_profit) < 0.01:
                print("  ✅ Profit matches expected value!")
            else:
                print(f"  ⚠️ Profit differs by ${abs(actual_profit - expected_profit):.2f}")
        else:
            print("❌ No profit data in summary")
        
        print()
        print("=" * 80)
        print("TEST COMPLETE")
        print("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        logger.exception(e)
    finally:
        if 'provider' in locals():
            await provider.disconnect()


if __name__ == "__main__":
    asyncio.run(test_trade_lifecycle())
