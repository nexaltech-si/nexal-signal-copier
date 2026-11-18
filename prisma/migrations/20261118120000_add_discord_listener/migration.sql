-- Discord signal source: the channels chosen per server in the dashboard, and a
-- local 32-bit id for every Discord message (snowflakes do not fit Signal.messageId).
-- Models in both schema.prisma files.
CREATE TABLE "discord_channels" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    "channelId" TEXT NOT NULL,
    "channelName" TEXT,
    "guildId" TEXT NOT NULL,
    "guildName" TEXT,
    "isActive" BOOLEAN NOT NULL DEFAULT true
);

CREATE UNIQUE INDEX "discord_channels_channelId_key" ON "discord_channels"("channelId");
CREATE INDEX "discord_channels_guildId_idx" ON "discord_channels"("guildId");

CREATE TABLE "discord_messages" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "channelId" TEXT NOT NULL,
    "messageId" TEXT NOT NULL
);

CREATE UNIQUE INDEX "discord_messages_messageId_key" ON "discord_messages"("messageId");
CREATE INDEX "discord_messages_channelId_id_idx" ON "discord_messages"("channelId", "id");
