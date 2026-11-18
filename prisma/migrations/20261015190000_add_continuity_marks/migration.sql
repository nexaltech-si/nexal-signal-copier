-- Signal-continuity marks that survive a restart (instant entries awaiting their
-- follow-up, deleted signals awaiting a repost). Model in both schema.prisma files.
CREATE TABLE "continuity_marks" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "kind" TEXT NOT NULL,
    "signalId" TEXT NOT NULL,
    "symbol" TEXT,
    "chatId" TEXT,
    "messageId" INTEGER,
    "expiresAt" DATETIME NOT NULL
);

CREATE INDEX "continuity_marks_kind_expiresAt_idx" ON "continuity_marks"("kind", "expiresAt");
CREATE INDEX "continuity_marks_signalId_idx" ON "continuity_marks"("signalId");
