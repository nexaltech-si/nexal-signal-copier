#!/usr/bin/env python3
"""
Get detailed information about specific Telegram channels
Usage: python scripts/get_channel_info.py <channel1> <channel2> ...
Examples:
  python scripts/get_channel_info.py @channel_username
  python scripts/get_channel_info.py -1001234567890
  python scripts/get_channel_info.py @channel1 @channel2 -1001234567890
"""
import asyncio
import sys
import os
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from config import settings


async def get_channel_info(client, channel_identifier):
    """
    Get detailed information about a specific channel
    
    Args:
        client: TelegramClient instance
        channel_identifier: Channel username (@channel) or ID (-1001234567890)
    """
    try:
        # Parse channel identifier
        parsed_id = channel_identifier
        if isinstance(channel_identifier, str) and channel_identifier.lstrip('-').isdigit():
            parsed_id = int(channel_identifier)
        
        # Get entity
        entity = await client.get_entity(parsed_id)
        
        info = {
            'input': channel_identifier,
            'success': True
        }
        
        if isinstance(entity, Channel):
            # Get full channel info
            try:
                full = await client(GetFullChannelRequest(entity))
                participants_count = full.full_chat.participants_count
                about = full.full_chat.about
            except Exception:
                participants_count = None
                about = None
            
            info.update({
                'type': 'broadcast_channel' if entity.broadcast else 'supergroup',
                'title': entity.title,
                'username': entity.username,
                'id': entity.id,
                'full_id': f"-100{entity.id}",
                'access_hash': entity.access_hash,
                'megagroup': entity.megagroup,
                'gigagroup': getattr(entity, 'gigagroup', False),
                'participants_count': participants_count,
                'about': about,
                'verified': entity.verified,
                'restricted': entity.restricted,
                'scam': entity.scam,
                'fake': entity.fake,
                'date': entity.date.isoformat() if hasattr(entity, 'date') else None
            })
            
        elif isinstance(entity, Chat):
            # Regular group
            try:
                full = await client(GetFullChatRequest(entity.id))
                participants_count = full.full_chat.participants.count if hasattr(full.full_chat, 'participants') else None
                about = full.full_chat.about if hasattr(full.full_chat, 'about') else None
            except Exception:
                participants_count = None
                about = None
            
            info.update({
                'type': 'group',
                'title': entity.title,
                'username': None,
                'id': entity.id,
                'full_id': str(entity.id),
                'participants_count': participants_count,
                'about': about,
                'date': entity.date.isoformat() if hasattr(entity, 'date') else None
            })
            
        elif isinstance(entity, User):
            info.update({
                'type': 'user',
                'title': f"{entity.first_name or ''} {entity.last_name or ''}".strip(),
                'username': entity.username,
                'id': entity.id,
                'full_id': str(entity.id),
                'access_hash': entity.access_hash,
                'bot': entity.bot,
                'verified': entity.verified,
                'restricted': entity.restricted,
                'scam': entity.scam,
                'fake': entity.fake,
                'phone': entity.phone
            })
        
        return info
        
    except Exception as e:
        return {
            'input': channel_identifier,
            'success': False,
            'error': str(e)
        }


async def main():
    """Main entry point"""
    
    # Check command line arguments
    if len(sys.argv) < 2:
        print("Usage: python scripts/get_channel_info.py <channel1> <channel2> ...")
        print("\nExamples:")
        print("  python scripts/get_channel_info.py @channel_username")
        print("  python scripts/get_channel_info.py -1001234567890")
        print("  python scripts/get_channel_info.py @channel1 @channel2 -1001234567890")
        print("\nOr use the configured channels from .env:")
        print("  python scripts/get_channel_info.py --from-config")
        sys.exit(1)
    
    print("=" * 80)
    print("  TELEGRAM CHANNEL INFO LOOKUP")
    print("=" * 80)
    print(f"\n📁 Using session: {settings.telegram_session_name}")
    
    # Create client
    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash
    )
    
    try:
        # Start client
        await client.start(phone=settings.telegram_phone)
        
        # Get authenticated user
        me = await client.get_me()
        print(f"✅ Logged in as: {me.first_name} (@{me.username or 'no username'})")
        
        # Determine which channels to look up
        if sys.argv[1] == '--from-config':
            channels_to_lookup = settings.telegram_channels
            print(f"\n📋 Looking up configured channels: {channels_to_lookup}")
        else:
            channels_to_lookup = sys.argv[1:]
            print(f"\n🔍 Looking up {len(channels_to_lookup)} channel(s)...")
        
        # Fetch info for each channel
        results = []
        for channel in channels_to_lookup:
            print(f"\n" + "=" * 80)
            print(f"Channel: {channel}")
            print("=" * 80)
            
            info = await get_channel_info(client, channel)
            results.append(info)
            
            if info['success']:
                print(f"✅ SUCCESS")
                print(f"\n📌 Basic Info:")
                print(f"   Type: {info['type']}")
                print(f"   Title: {info['title']}")
                print(f"   Username: @{info['username']}" if info.get('username') else "   Username: N/A (Private)")
                print(f"   ID: {info['id']}")
                print(f"   Full ID: {info['full_id']}")
                
                if info.get('participants_count'):
                    print(f"\n👥 Members: {info['participants_count']:,}")
                
                if info.get('about'):
                    print(f"\n📝 About:")
                    print(f"   {info['about'][:200]}{'...' if len(info['about']) > 200 else ''}")
                
                if info.get('verified'):
                    print("\n✓ Verified")
                
                if info.get('scam'):
                    print("\n⚠️ Marked as scam")
                
                if info.get('fake'):
                    print("\n⚠️ Marked as fake")
                
                if info.get('bot'):
                    print("\n🤖 This is a bot")
                
            else:
                print(f"❌ FAILED")
                print(f"   Error: {info['error']}")
        
        # Save results to JSON
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = os.path.join(output_dir, f'channel_info_{timestamp}.json')
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'fetched_at': datetime.utcnow().isoformat(),
                'user': {
                    'name': me.first_name,
                    'username': me.username,
                    'id': me.id
                },
                'results': results
            }, f, indent=2, ensure_ascii=False)
        
        print("\n" + "=" * 80)
        print("  SUMMARY")
        print("=" * 80)
        successful = sum(1 for r in results if r['success'])
        failed = len(results) - successful
        print(f"\n✅ Successful: {successful}")
        print(f"❌ Failed: {failed}")
        print(f"\n💾 Results saved to: {output_file}")
        
        await client.disconnect()
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        await client.disconnect()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
