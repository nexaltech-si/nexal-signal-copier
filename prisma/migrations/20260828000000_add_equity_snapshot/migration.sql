CREATE TABLE "equity_snapshots" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "balance" REAL NOT NULL,
    "equity" REAL NOT NULL,
    "margin" REAL NOT NULL,
    "freeMargin" REAL NOT NULL,
    "openPositions" INTEGER NOT NULL,
    "currency" TEXT NOT NULL DEFAULT 'USD'
);

CREATE INDEX "equity_snapshots_createdAt_idx" ON "equity_snapshots"("createdAt");
