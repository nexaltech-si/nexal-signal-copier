# 🐳 Docker Database Cleanup - Quick Guide

Your database is in a Docker container. Here's how to clean it up:

## 🚀 Easiest Way (Docker Interactive Script)

```bash
cd ~/telegram-trading-bot
./scripts/docker_cleanup.sh
```

**Menu options:**
1. Check database status ← Start here
2. Preview cleanup (safe, no changes)
3. Execute cleanup (will delete records)
4. Backup database
5. Cancel

---

## 📋 Manual Way (Inside Container)

### 1. Check Status
```bash
docker exec telegram-trading-bot python scripts/cleanup_keep_one_per_signal.py --status
```

### 2. Preview (Dry Run - Safe)
```bash
docker exec telegram-trading-bot python scripts/cleanup_keep_one_per_signal.py
```

### 3. Backup Database
```bash
# Create backup inside container
docker exec telegram-trading-bot cp /app/data/trading_bot.db /app/data/trading_bot.db.backup.$(date +%Y%m%d_%H%M%S)

# OR copy to host machine
docker cp telegram-trading-bot:/app/data/trading_bot.db ./data/trading_bot.db.backup.$(date +%Y%m%d_%H%M%S)
```

### 4. Execute Cleanup
```bash
docker exec -i telegram-trading-bot bash -c "echo 'DELETE' | python scripts/cleanup_keep_one_per_signal.py --execute"
```

### 5. Vacuum Database (Reclaim Space)
```bash
docker exec telegram-trading-bot sqlite3 /app/data/trading_bot.db "VACUUM;"
```

### 6. Verify Results
```bash
docker exec telegram-trading-bot python scripts/cleanup_keep_one_per_signal.py --status
```

---

## 🎯 One-Liner Cleanup (After Backup)

```bash
# Backup, cleanup, vacuum, verify - all in one
docker exec telegram-trading-bot cp /app/data/trading_bot.db /app/data/trading_bot.db.backup && \
docker exec -i telegram-trading-bot bash -c "echo 'DELETE' | python scripts/cleanup_keep_one_per_signal.py --execute" && \
docker exec telegram-trading-bot sqlite3 /app/data/trading_bot.db "VACUUM;" && \
docker exec telegram-trading-bot python scripts/cleanup_keep_one_per_signal.py --status
```

---

## 📊 Expected Results

### Before
```
Total Market Analyses:      45,823
Avg Analyses per Signal:    127.4
Database Size:              156 MB
```

### After
```
Total Market Analyses:      892      (95% reduction!)
Avg Analyses per Signal:    1.2      (perfect!)
Database Size:              8 MB     (95% smaller!)
```

---

## 🛡️ Safety Tips

1. **Always backup first!**
   ```bash
   docker cp telegram-trading-bot:/app/data/trading_bot.db ./backup_$(date +%Y%m%d).db
   ```

2. **Test with dry run:**
   ```bash
   docker exec telegram-trading-bot python scripts/cleanup_keep_one_per_signal.py
   ```

3. **Bot can stay running** - No need to stop it (but recommended to avoid locks)

4. **Restore if needed:**
   ```bash
   docker cp ./backup_20251015.db telegram-trading-bot:/app/data/trading_bot.db
   docker restart telegram-trading-bot
   ```

---

## 🔧 Docker Volume Info

Your database is stored in Docker volume: `db-data`

**Location inside container**: `/app/data/trading_bot.db`
**Volume**: `db-data:/app/data`

To inspect the volume:
```bash
# See volume details
docker volume inspect telegram-trading-bot_db-data

# List files in volume
docker exec telegram-trading-bot ls -lh /app/data/

# Check database size
docker exec telegram-trading-bot du -h /app/data/trading_bot.db
```

---

## ⚡ Quick Commands

```bash
# Status check
docker exec telegram-trading-bot python scripts/cleanup_keep_one_per_signal.py --status

# Backup
docker cp telegram-trading-bot:/app/data/trading_bot.db ./backup_$(date +%Y%m%d).db

# Cleanup (interactive script - easiest!)
./scripts/docker_cleanup.sh
```

---

## 🎉 After Cleanup

The optimization is already active to prevent this from happening again:
- ✅ Only saves when status changes
- ✅ 93-96% fewer database writes
- ✅ Table stays clean automatically

---

## ❓ Troubleshooting

### "Database is locked"
```bash
# Stop bot temporarily
docker-compose down
# Run cleanup
./scripts/docker_cleanup.sh
# Restart
docker-compose up -d
```

### "Container not found"
```bash
# Check container name
docker ps -a | grep bot

# Use correct container name in commands
docker exec <CORRECT_NAME> python scripts/cleanup_keep_one_per_signal.py --status
```

### "Permission denied"
```bash
# Make script executable
chmod +x scripts/docker_cleanup.sh
```

---

## 📚 Full Documentation

- **Docker Cleanup Guide**: `/docs/DATABASE_CLEANUP_GUIDE.md`
- **Before/After Comparison**: `/docs/BEFORE_AFTER_COMPARISON.md`
- **Optimization Details**: `/docs/AI_ANALYSIS_OPTIMIZATION.md`

---

**TL;DR**: Run `./scripts/docker_cleanup.sh` and choose option 3 (after backing up with option 4)!
