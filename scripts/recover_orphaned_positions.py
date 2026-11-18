#!/usr/bin/env python3
"""
Script to recover orphaned positions from MT5 and create database records
This fixes monitoring for positions that were opened outside the bot
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.integrations.trading.provider_factory import create_trading_provider
from src.core.database_service import db_service
from src.services.magic_number_service import magic_number_service
from datetime import datetime
from loguru import logger


async def recover_orphaned_positions():
    """Scan MT5 for positions without database records and create them"""
    
    logger.info("🔍 Starting orphaned position recovery...")
    
    # Initialize trading provider
    provider = create_trading_provider()
    await provider.initialize()
    
    # Get all open positions from MT5
    positions = await provider.get_open_positions(use_cache=False)
    logger.info(f"📊 Found {len(positions)} open position(s) in MT5")
    
    if not positions:
        logger.info("✅ No positions to recover")
        return
    
    recovered_count = 0
    skipped_count = 0
    
    for pos in positions:
        position_id = pos.get('id')
        symbol = pos.get('symbol')
        magic = pos.get('magic')
        
        logger.info(f"\n📍 Checking position {position_id} ({symbol}, magic: {magic})")
        
        # Check if trade record already exists
        existing_trade = await db_service.db.trade.find_first(
            where={'positionId': position_id}
        )
        
        if existing_trade:
            logger.info(f"  ⏭️  Trade record already exists: {existing_trade.id[:8]}...")
            skipped_count += 1
            continue
        
        # Create dummy signal for orphaned position
        logger.info(f"  📋 Creating dummy signal for orphaned position...")
        
        is_buy = pos.get('type') == 'POSITION_TYPE_BUY'
        action = "BUY" if is_buy else "SELL"
        
        dummy_signal = await db_service.db.signal.create(
            data={
                "action": "OPEN",
                "orderType": action,
                "symbol": symbol,
                "entryPrice": float(pos.get('openPrice', 0)),
                "stopLoss": float(pos.get('stopLoss', 0)) if pos.get('stopLoss') else None,
                "takeProfit": str(pos.get('takeProfit')) if pos.get('takeProfit') else None,
                "lotSize": float(pos.get('volume', 0)),
                "confidence": 0.5,
                "channelId": "MANUAL_RECOVERY",
                "channelName": "Manual Position Recovery",
                "messageId": magic if magic else 0,
                "rawMessage": f"[RECOVERED] {symbol} {action} position {position_id} recovered from MT5",
                "messageHash": f"recovery_{position_id}_{magic}",
                "status": "EXECUTED",
                "riskApproved": True
            }
        )
        
        logger.success(f"  ✅ Created dummy signal: {dummy_signal.id[:8]}...")
        
        # Create trade record
        trade_data = {
            "signalId": dummy_signal.id,
            "symbol": symbol,
            "action": action,
            "entryPrice": float(pos.get('openPrice', 0)),
            "stopLoss": float(pos.get('stopLoss', 0)) if pos.get('stopLoss') else None,
            "takeProfit": float(pos.get('takeProfit', 0)) if pos.get('takeProfit') else None,
            "originalStopLoss": float(pos.get('stopLoss', 0)) if pos.get('stopLoss') else None,
            "originalTakeProfit": float(pos.get('takeProfit', 0)) if pos.get('takeProfit') else None,
            "lotSize": float(pos.get('volume', 0)),
            "magicNumber": magic,
            "positionId": position_id,
            "status": "EXECUTED",
            "executedAt": datetime.now(),
            "lastModifiedAt": datetime.now(),
            # Enable auto monitoring
            "autoTpEnabled": True,
            "trailingStopEnabled": True,
            "breakEvenEnabled": True,
            "autoPartialEnabled": True
        }
        
        trade = await db_service.db.trade.create(data=trade_data)
        logger.success(f"  ✅ Created trade record: {trade.id[:8]}...")
        
        # Register with magic number service
        if magic:
            magic_number_service.register_order(
                magic_number=magic,
                position_id=position_id,
                symbol=symbol
            )
            logger.info(f"  📌 Registered with magic number service")
        
        # Log recovery action
        await db_service.log_trade_action(
            trade_id=trade.id,
            action_type='RECOVERY',
            success=True,
            triggered_by='manual_recovery_script',
            trigger_source='orphaned_position_recovery',
            details=f"Recovered orphaned position {position_id} (magic: {magic}, symbol: {symbol})"
        )
        
        recovered_count += 1
        logger.success(f"  ✅ Position {position_id} recovered successfully!")
    
    logger.info(f"\n{'='*70}")
    logger.success(f"✅ Recovery complete!")
    logger.info(f"   Recovered: {recovered_count}")
    logger.info(f"   Skipped: {skipped_count}")
    logger.info(f"   Total: {len(positions)}")
    logger.info(f"{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(recover_orphaned_positions())
