-- Trade copier: mirror accounts reporting in from NexalSignalMirrorEA v2+ and
-- their action log. Models live in dashboard/prisma/schema.prisma (like ApiKey).

-- CreateTable
CREATE TABLE "ea_accounts" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    "apiKeyId" TEXT NOT NULL,
    "login" TEXT NOT NULL,
    "server" TEXT NOT NULL,
    "broker" TEXT,
    "name" TEXT,
    "currency" TEXT,
    "leverage" INTEGER,
    "eaVersion" TEXT,
    "mode" TEXT,
    "halted" BOOLEAN NOT NULL DEFAULT false,
    "sizing" TEXT,
    "pollSeconds" INTEGER,
    "reportSeconds" INTEGER,
    "balance" REAL,
    "equity" REAL,
    "margin" REAL,
    "freeMargin" REAL,
    "lastSeenAt" DATETIME NOT NULL,
    "lastIp" TEXT,
    "feedOk" BOOLEAN NOT NULL DEFAULT true,
    "pollFailures" INTEGER NOT NULL DEFAULT 0,
    "lastError" TEXT,
    "positionsCount" INTEGER NOT NULL DEFAULT 0,
    "ordersCount" INTEGER NOT NULL DEFAULT 0,
    "links" TEXT,
    CONSTRAINT "ea_accounts_apiKeyId_fkey" FOREIGN KEY ("apiKeyId") REFERENCES "api_keys" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "ea_events" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "accountId" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "symbol" TEXT,
    "masterTicket" TEXT,
    "mirrorTicket" TEXT,
    "message" TEXT NOT NULL,
    CONSTRAINT "ea_events_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "ea_accounts" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "ea_accounts_apiKeyId_login_server_key" ON "ea_accounts"("apiKeyId", "login", "server");

-- CreateIndex
CREATE INDEX "ea_accounts_lastSeenAt_idx" ON "ea_accounts"("lastSeenAt");

-- CreateIndex
CREATE INDEX "ea_events_accountId_createdAt_idx" ON "ea_events"("accountId", "createdAt");
