#!/usr/bin/env python3
"""Check APPROVAL_CHANNEL_ID in database"""
import asyncio
import sys
from src.core.prisma_client import prisma_client

async def check_setting():
    try:
        await prisma_client.initialize()
        setting = await prisma_client.client.setting.find_unique(where={'key': 'APPROVAL_CHANNEL_ID'})
        if setting:
            print(f'✅ Found APPROVAL_CHANNEL_ID:')
            print(f'   Key: {setting.key}')
            print(f'   Value: {setting.value}')
            print(f'   ValueType: {setting.valueType}')
            print(f'   IsSecret: {setting.isSecret}')
        else:
            print('❌ APPROVAL_CHANNEL_ID not found in database')
    finally:
        await prisma_client.client.disconnect()

asyncio.run(check_setting())
