#!/usr/bin/env python3
"""
Fetch all Telegram channel details (name, ID, username)
Saves session in the sessions folder and exports results to JSON
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
from config import settings


async def fetch_all_channels():
    """Fetch all channels, groups, and chats from Telegram"""
    
    print("=" * 80)
    print("  TELEGRAM CHANNEL DETAILS FETCHER")
    print("=" * 80)
    print(f"\n📁 Session will be saved in: {settings.telegram_session_name}")
    
    # Create client with session in sessions folder
    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash
    )
    
    try:
        # Start client and authenticate
        await client.start(phone=settings.telegram_phone)
        
        # Get authenticated user info
        me = await client.get_me()
        print(f"\n✅ Logged in as: {me.first_name} (@{me.username or 'no username'})")
        print(f"   User ID: {me.id}")
        print(f"   Phone: {me.phone}")
        
        print("\n" + "=" * 80)
        print("  FETCHING ALL DIALOGS...")
        print("=" * 80)
        
        # Fetch all dialogs
        dialogs = await client.get_dialogs()
        print(f"\n📊 Total dialogs found: {len(dialogs)}")
        
        # Categorize entities
        channels = []
        supergroups = []
        groups = []
        private_chats = []
        
        for dialog in dialogs:
            entity = dialog.entity
            
            if isinstance(entity, Channel):
                if entity.broadcast:
                    # It's a broadcast channel
                    channels.append({
                        'title': entity.title,
                        'username': entity.username,
                        'id': entity.id,
                        'access_hash': entity.access_hash,
                        'megagroup': entity.megagroup,
                        'participants_count': getattr(entity, 'participants_count', None)
                    })
                else:
                    # It's a supergroup (large group)
                    supergroups.append({
                        'title': entity.title,
                        'username': entity.username,
                        'id': entity.id,
                        'access_hash': entity.access_hash,
                        'megagroup': entity.megagroup,
                        'participants_count': getattr(entity, 'participants_count', None)
                    })
            elif isinstance(entity, Chat):
                # Regular group
                groups.append({
                    'title': entity.title,
                    'username': None,
                    'id': entity.id,
                    'participants_count': getattr(entity, 'participants_count', None)
                })
            elif isinstance(entity, User) and not entity.is_self:
                # Private chat with a user
                private_chats.append({
                    'title': entity.first_name or 'Unknown',
                    'username': entity.username,
                    'id': entity.id,
                    'access_hash': entity.access_hash,
                    'bot': entity.bot
                })
        
        # Prepare results
        results = {
            'fetched_at': datetime.utcnow().isoformat(),
            'user_info': {
                'name': me.first_name,
                'username': me.username,
                'id': me.id,
                'phone': me.phone
            },
            'statistics': {
                'total_dialogs': len(dialogs),
                'channels': len(channels),
                'supergroups': len(supergroups),
                'groups': len(groups),
                'private_chats': len(private_chats)
            },
            'channels': channels,
            'supergroups': supergroups,
            'groups': groups,
            'private_chats': private_chats
        }
        
        # Display summary
        print("\n" + "=" * 80)
        print("  SUMMARY")
        print("=" * 80)
        print(f"\n📢 Channels: {len(channels)}")
        print(f"💬 Supergroups: {len(supergroups)}")
        print(f"👥 Groups: {len(groups)}")
        print(f"👤 Private Chats: {len(private_chats)}")
        
        # Display channels
        if channels:
            print("\n" + "=" * 80)
            print("  BROADCAST CHANNELS")
            print("=" * 80)
            for idx, ch in enumerate(channels, 1):
                print(f"\n{idx}. {ch['title']}")
                print(f"   Username: @{ch['username']}" if ch['username'] else "   Username: N/A (Private)")
                print(f"   ID: {ch['id']}")
                print(f"   Full ID: -100{ch['id']}")
                if ch['participants_count']:
                    print(f"   Members: {ch['participants_count']:,}")
        
        # Display supergroups
        if supergroups:
            print("\n" + "=" * 80)
            print("  SUPERGROUPS")
            print("=" * 80)
            for idx, sg in enumerate(supergroups, 1):
                print(f"\n{idx}. {sg['title']}")
                print(f"   Username: @{sg['username']}" if sg['username'] else "   Username: N/A (Private)")
                print(f"   ID: {sg['id']}")
                print(f"   Full ID: -100{sg['id']}")
                if sg['participants_count']:
                    print(f"   Members: {sg['participants_count']:,}")
        
        # Display regular groups (limited to first 10)
        if groups:
            print("\n" + "=" * 80)
            print("  GROUPS (First 10)")
            print("=" * 80)
            for idx, grp in enumerate(groups[:10], 1):
                print(f"\n{idx}. {grp['title']}")
                print(f"   ID: {grp['id']}")
                if grp['participants_count']:
                    print(f"   Members: {grp['participants_count']:,}")
        
        # Display private chats (limited to first 10)
        if private_chats:
            print("\n" + "=" * 80)
            print("  PRIVATE CHATS (First 10)")
            print("=" * 80)
            for idx, pc in enumerate(private_chats[:10], 1):
                bot_label = " [BOT]" if pc.get('bot') else ""
                print(f"\n{idx}. {pc['title']}{bot_label}")
                print(f"   Username: @{pc['username']}" if pc['username'] else "   Username: N/A")
                print(f"   ID: {pc['id']}")
        
        # Save to JSON file
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = os.path.join(output_dir, f'telegram_channels_{timestamp}.json')
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print("\n" + "=" * 80)
        print("  EXPORT COMPLETE")
        print("=" * 80)
        print(f"\n💾 Results saved to: {output_file}")
        print(f"📁 Session saved in: {settings.telegram_session_name}")
        
        # Display useful tips
        print("\n" + "=" * 80)
        print("  USAGE TIPS")
        print("=" * 80)
        print("\n💡 To monitor a channel in your .env file, use:")
        print("   - Username format: @channel_username")
        print("   - ID format: -100XXXXXXXXXX (for channels/supergroups)")
        print("   - ID format: -XXXXXXXXX (for regular groups)")
        print("\n📋 Example .env configuration:")
        print("   TELEGRAM_CHANNEL_ID=@channel1,@channel2,-1001234567890")
        
        await client.disconnect()
        
        return results
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        await client.disconnect()
        return None


async def main():
    """Main entry point"""
    results = await fetch_all_channels()
    
    if results:
        print("\n✅ Script completed successfully!")
    else:
        print("\n❌ Script failed!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
