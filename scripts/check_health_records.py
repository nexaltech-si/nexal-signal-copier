#!/usr/bin/env python3
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from prisma import Prisma
from datetime import datetime, timedelta
import json


async def check_health_records():
    """Check SystemHealth and SystemEvent records for health checks"""
    db = Prisma()
    await db.connect()
    
    try:
        print("=" * 80)
        print("SYSTEM HEALTH RECORDS")
        print("=" * 80)
        
        # Get all SystemHealth records
        health_records = await db.systemhealth.find_many(
            order={
                'updatedAt': 'desc'
            },
            take=10
        )
        
        if health_records:
            print(f"\nFound {len(health_records)} SystemHealth record(s):\n")
            for record in health_records:
                print(f"ID: {record.id}")
                print(f"Status: {record.overallStatus}")
                print(f"Last Check: {record.lastCheck}")
                print(f"Updated At: {record.updatedAt}")
                print(f"Total Components: {record.totalComponents}")
                print(f"Healthy: {record.healthyComponents}")
                print(f"Degraded: {record.degradedComponents}")
                print(f"Unhealthy: {record.unhealthyComponents}")
                print(f"Unknown: {record.unknownComponents}")
                
                # Parse components JSON
                try:
                    components = json.loads(record.components)
                    print("\nComponent Details:")
                    for comp_name, comp_data in components.items():
                        print(f"  {comp_name}:")
                        print(f"    Status: {comp_data.get('status', 'N/A')}")
                        print(f"    Stability: {comp_data.get('stability', 'N/A')}")
                        if comp_data.get('lastError'):
                            print(f"    Last Error: {comp_data.get('lastError')}")
                        if comp_data.get('lastSync'):
                            print(f"    Last Sync: {comp_data.get('lastSync')}")
                except json.JSONDecodeError:
                    print(f"\nComponents (raw): {record.components[:200]}...")
                
                print("-" * 80)
        else:
            print("\n⚠️  NO SystemHealth records found in database!")
            print("This indicates the health monitoring is NOT writing to the database.")
        
        print("\n" + "=" * 80)
        print("RECENT SYSTEM EVENTS (Health-related)")
        print("=" * 80)
        
        # Get recent health-related system events
        recent_time = datetime.now() - timedelta(hours=24)
        events = await db.systemevent.find_many(
            where={
                'OR': [
                    {'eventType': 'ERROR'},
                    {'eventType': 'WARNING'},
                ],
                'createdAt': {
                    'gte': recent_time
                }
            },
            order={
                'createdAt': 'desc'
            },
            take=20
        )
        
        if events:
            print(f"\nFound {len(events)} recent event(s) (last 24h):\n")
            for event in events:
                print(f"[{event.createdAt}] {event.eventType} - {event.severity}")
                print(f"Message: {event.message}")
                if event.module:
                    print(f"Module: {event.module}")
                if event.details:
                    try:
                        details = json.loads(event.details)
                        print(f"Details: {json.dumps(details, indent=2)}")
                    except Exception:
                        print(f"Details: {event.details[:200]}...")
                print("-" * 80)
        else:
            print("\nNo recent health-related events found.")
        
        # Count total events
        total_events = await db.systemevent.count()
        print(f"\nTotal SystemEvent records in database: {total_events}")
        
        total_health = await db.systemhealth.count()
        print(f"Total SystemHealth records in database: {total_health}")
        
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(check_health_records())
