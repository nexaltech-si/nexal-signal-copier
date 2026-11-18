"""
Database side of the Discord listener: which channels are monitored, and the
local message ids (see events.py for why Discord ids are not used directly).
"""
from typing import Dict, Iterable, List, Optional

from loguru import logger

from src.core.prisma_client import prisma_client


# Local ids start far above any Telegram message id. Order magic numbers derive from
# the message id alone (magic_number_service: id % 100_000_000), so a Discord message
# sharing a small id with a Telegram post would share its magic number, and a reply in
# one source could manage the other's trades. Ids stay below 100M (the magic range) and
# below 114M (split-post ids must fit 32 bits, see src/utils/split_ids.py).
LOCAL_ID_BASE = 50_000_000


def _db():
    return prisma_client.client


def _channel_dict(row) -> dict:
    return {
        "channelId": row.channelId,
        "channelName": row.channelName,
        "guildId": row.guildId,
        "guildName": row.guildName,
        "isActive": row.isActive,
    }


class DiscordStore:
    # ------------------------------------------------------------ channels

    async def monitored_channels(self) -> List[dict]:
        rows = await _db().discordchannel.find_many(where={"isActive": True}, order={"createdAt": "asc"})
        return [_channel_dict(r) for r in rows]

    async def set_guild_channels(self, guild_id: str, guild_name: Optional[str], channels: List[dict]) -> List[dict]:
        """Replace the monitored channels of one server. `channels`: [{"id", "name"}]."""
        wanted = {str(c["id"]): c.get("name") for c in channels}
        existing = await _db().discordchannel.find_many(where={"guildId": guild_id})
        for row in existing:
            if row.channelId not in wanted:
                await _db().discordchannel.delete(where={"channelId": row.channelId})
        for channel_id, name in wanted.items():
            data = {"channelName": name, "guildId": guild_id, "guildName": guild_name, "isActive": True}
            await _db().discordchannel.upsert(
                where={"channelId": channel_id},
                data={"create": {"channelId": channel_id, **data}, "update": data},
            )
        return await self.monitored_channels()

    async def remove_channel(self, channel_id: str) -> bool:
        deleted = await _db().discordchannel.delete_many(where={"channelId": channel_id})
        return bool(deleted)

    async def rename(self, channel_id: str, channel_name: str, guild_name: Optional[str]) -> None:
        """Keep the stored names in step with Discord (servers and channels get renamed)."""
        try:
            await _db().discordchannel.update_many(
                where={"channelId": channel_id}, data={"channelName": channel_name, "guildName": guild_name}
            )
        except Exception as e:
            logger.debug(f"Discord: could not update channel name {channel_id}: {e}")

    # ------------------------------------------------------------ message ids

    async def local_id(self, channel_id: int, message_id: int) -> int:
        """The local id of a Discord message, allocated on first sight."""
        row = await _db().discordmessage.upsert(
            where={"messageId": str(message_id)},
            data={"create": {"channelId": str(channel_id), "messageId": str(message_id)}, "update": {}},
        )
        return LOCAL_ID_BASE + row.id

    async def known_local_id(self, message_id: int) -> Optional[int]:
        row = await _db().discordmessage.find_unique(where={"messageId": str(message_id)})
        return LOCAL_ID_BASE + row.id if row else None

    async def snowflake_for(self, local_id: int) -> Optional[int]:
        """The Discord message id behind a local id."""
        row = await _db().discordmessage.find_unique(where={"id": int(local_id) - LOCAL_ID_BASE})
        return int(row.messageId) if row else None

    async def known_local_ids(self, message_ids: Iterable[int]) -> Dict[int, int]:
        rows = await _db().discordmessage.find_many(where={"messageId": {"in": [str(m) for m in message_ids]}})
        return {int(r.messageId): LOCAL_ID_BASE + r.id for r in rows}


discord_store = DiscordStore()
