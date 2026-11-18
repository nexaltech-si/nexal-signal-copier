-- API key connection log: one row per (key, client IP, status), updated in
-- place on repeat requests, instead of a row per request. Existing rows are
-- collapsed into that shape (hits = number of old rows, not requests).
-- Model lives in dashboard/prisma/schema.prisma (like ApiKey).

PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;

CREATE TABLE "new_api_key_usage" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastSeenAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "hits" INTEGER NOT NULL DEFAULT 1,
    "apiKeyId" TEXT NOT NULL,
    "ip" TEXT,
    "userAgent" TEXT,
    "endpoint" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    CONSTRAINT "api_key_usage_apiKeyId_fkey" FOREIGN KEY ("apiKeyId") REFERENCES "api_keys" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

INSERT INTO "new_api_key_usage" ("id", "createdAt", "lastSeenAt", "hits", "apiKeyId", "ip", "userAgent", "endpoint", "status")
SELECT "id", "firstSeen", "createdAt", "n", "apiKeyId", "ip", "userAgent", "endpoint", "status"
FROM (
    SELECT u.*,
        MIN(u."createdAt") OVER g AS "firstSeen",
        COUNT(*) OVER g AS "n",
        ROW_NUMBER() OVER (PARTITION BY u."apiKeyId", u."ip", u."status" ORDER BY u."createdAt" DESC) AS "rn"
    FROM "api_key_usage" u
    WINDOW g AS (PARTITION BY u."apiKeyId", u."ip", u."status")
)
WHERE "rn" = 1;

DROP TABLE "api_key_usage";
ALTER TABLE "new_api_key_usage" RENAME TO "api_key_usage";

CREATE UNIQUE INDEX "api_key_usage_apiKeyId_ip_status_key" ON "api_key_usage"("apiKeyId", "ip", "status");
CREATE INDEX "api_key_usage_apiKeyId_lastSeenAt_idx" ON "api_key_usage"("apiKeyId", "lastSeenAt");

PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;
