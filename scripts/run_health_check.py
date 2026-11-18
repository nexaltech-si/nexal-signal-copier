"""
Quick script to run a health check and populate the database
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.health_check_service import health_check_service
from src.core.prisma_client import prisma_client
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def main():
    """Run a single health check"""
    logger.info("🏥 Running health check...")
    
    try:
        # Initialize database
        await prisma_client.initialize()
        
        # Configure health check service with minimal components
        health_check_service.set_components(
            prisma_client=prisma_client
        )
        
        # Run all checks once
        health_status = await health_check_service.run_all_checks()
        
        # Display results
        logger.info("=" * 60)
        logger.info(f"Overall Status: {health_status['overall_status'].upper()}")
        logger.info(f"Last Check: {health_status['last_check']}")
        logger.info("\n📋 Component Status:")
        logger.info("-" * 60)
        
        for name, component in health_status['components'].items():
            status_emoji = {
                'healthy': '✅',
                'degraded': '⚠️',
                'unhealthy': '❌',
                'unknown': '❓'
            }.get(component['status'], '❓')
            
            logger.info(f"{status_emoji} {name:20s} - {component['status'].upper()}")
            logger.info(f"   Message: {component['message']}")
        
        logger.info("\n✅ Health check completed and saved to database!")
        logger.info("   Refresh your dashboard to see the results.")
        
    except Exception as e:
        logger.error(f"\n❌ Health check failed: {e}", exc_info=True)
    finally:
        # Cleanup
        await prisma_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
