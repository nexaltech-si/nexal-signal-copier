# Telegram Trading Bot Dashboard API Documentation

This document provides a comprehensive guide to the API endpoints available in the Telegram Trading Bot Dashboard. All endpoints are relative to the `/api` base path.

## Table of Contents
1. [Trades](#1-trades)
2. [Signals](#2-signals)
3. [Analytics & Stats](#3-analytics--stats)
4. [Settings & Configuration](#4-settings--configuration)
5. [System & Health](#5-system--health)
6. [Data Cleaning & Maintenance](#6-data-cleaning--maintenance)

---

## 1. Trades

### GET `/api/trades`
Fetches a list of trades with optional filtering.

**Query Parameters:**
- `limit` (optional): Number of records to return (default: 50).
- `offset` (optional): Number of records to skip (default: 0).
- `status` (optional): Filter by trade status (e.g., `EXECUTED`, `CLOSED`).
- `symbol` (optional): Filter by trading symbol.
- `channel` (optional): Filter by channel ID or Name.
- `outcome` (optional): Filter by trade outcome (`win`, `loss`, `breakeven`).

**Response:** Array of `Trade` objects including `signal`, `tradeActions`, and `marketAnalyses`.

---

### GET `/api/trades/[id]`
Fetches details for a specific trade.

**Response:** A single `Trade` object with all associated data.

---

### PATCH `/api/trades/[id]`
Updates a specific trade's status or notes.

**Request Body:**
```json
{
  "status": "CLOSED",
  "notes": "Manual intervention"
}
```

**Response:** The updated `Trade` object.

---

### DELETE `/api/trades/[id]`
Deletes a specific trade and its associated actions.

**Response:** Success message.

---

### GET `/api/trade-actions`
Fetches a history of all trade operations (entries, exits, modifications).

**Query Parameters:**
- `tradeId` (optional): Filter by specific trade.
- `actionType` (optional): Filter by type (e.g., `ENTRY`, `EXIT`).
- `triggeredBy` (optional): Filter by agent/user who triggered the action.

---

## 2. Signals

### GET `/api/signals`
Fetches a list of signals received from Telegram channels.

**Query Parameters:**
- `limit`, `offset` (optional): Pagination.
- `status` (optional): Filter by status.
- `symbol` (optional): Filter by symbol.
- `verification` (optional): Filter by AI verification status (`verified`, `unverified`).
- `dateFrom`, `dateTo` (optional): Date range filtering.

**Response:** Array of `Signal` objects including `trades` and `replies`.

---

### GET `/api/signals/[id]`
Fetches details for a specific signal.

---

### DELETE `/api/signals/[id]`
Deletes a signal and all related trades and actions.

---

### POST `/api/signals/verify`
Manually triggers AI verification for a specific signal.

**Request Body:**
```json
{
  "signalId": "uuid-here"
}
```

---

### POST `/api/signals/auto-verify`
Triggers AI verification for all unverified signals.

---

## 3. Analytics & Stats

### GET `/api/stats`
Returns high-level summary statistics for the dashboard.

**Response contains:**
- Total signals/trades counts.
- Win rate calculation.
- Profit/Loss summary.
- Recent trading sessions.
- Performance by symbol.

---

### GET `/api/performance`
Fetches historical performance data for charting.

**Query Parameters:**
- `period` (optional): Time period (e.g., `7d`, `30d`, `all`).

---

### GET `/api/analytics`
Detailed trading analytics and metrics.

---

### GET `/api/drawdown`
Fetches drawdown status and breach history.

---

### GET `/api/cot`
Fetches Commitment of Traders (COT) data for sentiment analysis.

---

### GET `/api/ai-analysis`
Fetches AI-generated market analyses for trades.

---

## 4. Settings & Configuration

### GET `/api/balances`
Fetches current balances across all configured trading accounts.

---

### GET `/api/provider`
Lists all unique signal providers found in the database.

---

### GET `/api/channels`
Lists all unique Telegram channels found in the database.

---

### GET `/api/filter-options`
Returns available options for dropdown filters (symbols, channels, statuses).

---

## 5. System & Health

### GET `/api/health`
Returns the current health status of all system components.

**Response contains:**
- `overallStatus`: healthy, degraded, or unhealthy.
- `components`: Status of Database, MetaAPI, AI Service, etc.
- `lastCheck`: Timestamp of last health check.

---

### GET `/api/logs`
Fetches system logs with optional level filtering.

---

## 6. Data Cleaning & Maintenance

### POST `/api/cleanup`
Clean up old data or stale trades.

---

### POST `/api/fix-database`
Scans for and fixes common database inconsistencies (e.g., trades without signals).
