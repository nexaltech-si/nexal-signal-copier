-- Which trading provider/account executed each trade.
ALTER TABLE "trades" ADD COLUMN "provider" TEXT;
CREATE INDEX "trades_provider_idx" ON "trades"("provider");
