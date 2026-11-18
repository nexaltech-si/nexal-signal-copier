-- AI vision toggle on the AI configuration. The field was added to both
-- schema.prisma files on 2026-05-27 (d71c4fc) without a migration, so every
-- read of ai_configuration failed with P2022 ("column does not exist").
ALTER TABLE "ai_configuration" ADD COLUMN "enableAIVision" BOOLEAN NOT NULL DEFAULT true;
