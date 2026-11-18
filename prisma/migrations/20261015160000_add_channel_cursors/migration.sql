-- Last handled Telegram message per monitored channel (catch-up after downtime).
-- Model lives in prisma/schema.prisma and dashboard/prisma/schema.prisma.

CREATE TABLE "channel_cursors" (
    "channelId" TEXT NOT NULL PRIMARY KEY,
    "lastMessageId" INTEGER NOT NULL,
    "lastMessageAt" DATETIME,
    "updatedAt" DATETIME NOT NULL
);
