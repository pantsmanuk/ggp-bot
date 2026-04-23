# Garbage Collection (GC) Implementation Plan

**Status**: Design Complete, Ready for Implementation  
**Created**: April 23, 2026  
**Context**: Production incident investigation revealed lack of database cleanup contributed to potential issues with token cache, lunch timers, and timeclock state persistence.

---

## Background & Context

### The Incident (April 22-23, 2026)

A production deployment experienced a mysterious token loss incident:

1. **16:56** - Staging database files copied to `/var/lib/ggp-bot/`
2. **17:43** - Bot started as systemd service
3. **17:43-09:00** - Bot ran but couldn't connect to Slack (15-hour gap in logs)
4. **09:00** - Bot finally connected, user's token showed as "not linked"
5. **09:00:32** - User reconnected, new token created, old token data lost

**Root cause remains uncertain**, but investigation revealed:
- No garbage collection exists for any of the three SQLite databases
- Lunch timers and timeclock state persist indefinitely across days
- Token cache has no integrity checking beyond basic expiry
- Limited audit logging made forensic analysis difficult

### Current State of Databases

| Database | Purpose | Current GC | Issues |
|----------|---------|------------|--------|
| `tokens.db` | Encrypted user tokens | Only expired token removal on access | No proactive integrity checks |
| `lunch_timers.db` | Active lunch break timers | NONE | Persists across days, reloads on restart |
| `timeclock_state.db` | #Attendance posting state | NONE | Accumulates forever, stale state possible |

---

## Requirements

### From Product Owner

1. **Token Database (`tokens.db`)**
   - Tokens persist as long as user is in Slack/staff member
   - NO automatic expiration/cleanup beyond API-level expiry
   - Admin command to manually expire users from cache
   - Validation/integrity checking on access
   - No assumption about scopes - confirm with API

2. **Lunch Timers (`lunch_timers.db`)**
   - NO timers last longer than any calendar day
   - Clean entire cache at 06:00 daily
   - Rationale: Users don't work overnight

3. **Time Clock State (`timeclock_state.db`)**
   - NO state persists overnight
   - Clean entire cache at 06:00 daily
   - Rationale: #Attendance shows "today's" status

4. **Implementation Approach**
   - "Cron" inside the bot, not external
   - Follow existing `lunch_timer.py` background task pattern
   - No naive cache invalidation at startup (could lose data)

---

## Proposed Architecture

### New Module: `src/ggp_bot/db_cleanup/scheduler.py`

Following the `LunchTimerManager` pattern:

```python
class DatabaseCleanupScheduler:
    """Manages daily cleanup tasks for all SQLite databases."""
    
    def __init__(self):
        self._cleanup_task: Optional[asyncio.Task] = None
        
    def start(self) -> None:
        """Start the daily cleanup background task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    def stop(self) -> None:
        """Stop the cleanup background task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
    
    async def _cleanup_loop(self) -> None:
        """Main loop - runs daily at 06:00."""
        while True:
            # Calculate seconds until next 06:00
            now = datetime.now()
            next_run = now.replace(hour=6, minute=0, second=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            
            wait_seconds = (next_run - now).total_seconds()
            logger.info(f"Next GC scheduled for {next_run}")
            
            await asyncio.sleep(wait_seconds)
            await self._perform_cleanup()
    
    async def _perform_cleanup(self) -> None:
        """Execute cleanup tasks."""
        logger.info("Starting daily database cleanup (06:00)...")
        
        # 1. Lunch timers - clear ALL (daily reset)
        await self._cleanup_lunch_timers()
        
        # 2. Timeclock state - clear ALL (daily reset)
        await self._cleanup_timeclock_state()
        
        # 3. Token cache - audit only, no cleanup
        await self._audit_token_cache()
        
        logger.info("Daily database cleanup completed")
```

### Integration Points

1. **Start in `app.py`** (similar to lunch_timer):
   ```python
   from ggp_bot.db_cleanup.scheduler import cleanup_scheduler
   
   async def start_app(...):
       # ... existing code ...
       cleanup_scheduler.start()
   
   async def shutdown_app():
       cleanup_scheduler.stop()
       # ... existing code ...
   ```

2. **Stop in `main.py`** (graceful shutdown):
   Already handled via `shutdown_app()` → `cleanup_scheduler.stop()`

---

## Implementation Tasks

### Phase 1: Core GC Scheduler (Priority: HIGH)

- [ ] Create `src/ggp_bot/db_cleanup/__init__.py`
- [ ] Create `src/ggp_bot/db_cleanup/scheduler.py`
  - [ ] `DatabaseCleanupScheduler` class with `start()`/`stop()` methods
  - [ ] `_cleanup_loop()` - sleep until 06:00 daily
  - [ ] `_cleanup_lunch_timers()` - DELETE FROM lunch_timers
  - [ ] `_cleanup_timeclock_state()` - DELETE FROM timeclock_notifications
  - [ ] `_audit_token_cache()` - report only, no deletion
  - [ ] Proper error handling and logging
- [ ] Integrate into `app.py` startup/shutdown
- [ ] Add INFO-level logging for all GC operations

**Audit Logging Pattern to Use:**
```python
logger.info(f"GC: Removed {count} lunch timers from database")
logger.info(f"GC: Removed {count} timeclock state records")
logger.info(f"GC: Token audit - {valid} valid, {issues} with warnings")
```

### Phase 2: Token Integrity Improvements (Priority: HIGH)

- [ ] Enhance `token_storage.py` `get_token()` method:
  - [ ] Add validation for empty/missing scopes (log WARNING, don't delete)
  - [ ] Add token age calculation and logging
  - [ ] Ensure `is_expired` check logs detailed metadata before removal
- [ ] Add `validate_all_tokens()` method for proactive integrity checking
  - [ ] Check: can_decrypt, has_scopes, not_expired
  - [ ] Return report dict without modifying database
- [ ] Ensure all token operations use "TOKEN AUDIT:" log prefix

**Current State (already implemented):**
- ✅ Token decryption failure logging (ERROR level with metadata)
- ✅ Token expiry logging (INFO with age, timestamps)
- ✅ Token save/update audit trail
- ✅ `remove_token()` with reason parameter
- ✅ `log_token_audit_summary()` method

**Still Needed:**
- Integrity checking on access (empty scopes detection)
- Proactive weekly/monthly audit task

### Phase 3: Admin Commands (Priority: MEDIUM)

- [ ] Add `ADMIN_SUBCOMMANDS` to `commands.py`:
  ```python
  ADMIN_SUBCOMMANDS = {
      "cache": {
          "clear": "Remove specific user from token cache",
          "status": "Show token cache statistics",
      },
      "gc": {
          "status": "Show GC schedule and last run",
          "run": "Manually trigger GC",
      },
      "integrity": {
          "check": "Validate all databases",
      },
  }
  ```

- [ ] Implement handlers:
  - [ ] `_handle_admin_cache_clear()` - `token_storage.remove_token()`
  - [ ] `_handle_admin_cache_status()` - `token_storage.get_stats()`
  - [ ] `_handle_admin_gc_status()` - scheduler status
  - [ ] `_handle_admin_gc_run()` - manual `_perform_cleanup()`
  - [ ] `_handle_admin_integrity_check()` - validate all DBs

- [ ] Add to `_get_all_command_names()` for suggestion system
- [ ] Add help text in `_handle_help_subcommand()`

### Phase 4: Documentation (Priority: MEDIUM)

- [ ] Update `README.md` with admin command reference
- [ ] Update `DEPLOY.md` with GC behavior explanation
- [ ] Document `/ggp admin` commands in help system

---

## Key Design Decisions

### 1. No Startup Cleanup

**Decision**: DO NOT clean caches at bot startup.  
**Rationale**: Data loss risk. If bot restarts at 05:00, legitimate timers/state would be lost. Scheduled 06:00 cleanup is safer.

### 2. Token Cache Persistence

**Decision**: Tokens NEVER auto-delete except on API-reported expiry.  
**Rationale**: Forcing users to re-link is poor UX. Admin intervention only.

### 3. Daily GC at 06:00

**Decision**: 06:00 local time for all caches.  
**Rationale**: Before typical workday start (09:00), after any night shift activity. Configurable if needed later.

### 4. Background Task Pattern

**Decision**: Follow `lunch_timer.py` exactly.  
**Rationale**: Consistency with existing codebase. Proven pattern with proper asyncio integration.

### 5. Admin Command Security

**Decision**: Any linked user can run admin commands (for now).  
**Rationale**: Simplest implementation. Can add admin whitelist later if needed.

**Alternative considered**: Restrict to specific Slack user IDs via env var:
```python
ADMIN_SLACK_IDS = os.getenv("ADMIN_SLACK_IDS", "").split(",")
if slack_user_id not in ADMIN_SLACK_IDS:
    await respond(":x: Admin commands restricted.")
    return
```

---

## Files to Modify

### New Files
```
src/ggp_bot/db_cleanup/
├── __init__.py          # Export cleanup_scheduler
└── scheduler.py         # DatabaseCleanupScheduler class
```

### Modified Files
```
src/ggp_bot/slack/app.py              # Add scheduler start/stop
src/ggp_bot/slack/handlers/commands.py # Add /ggp admin commands
src/ggp_bot/intranet/token_storage.py  # Enhance integrity checking
```

---

## Testing Plan

### Manual Testing
1. Deploy to staging
2. Start bot, verify "Next GC scheduled for..." log at INFO level
3. Create lunch timer, verify it's in DB
4. Wait for 06:00 (or temporarily change schedule for testing)
5. Verify lunch timer removed from DB
6. Create timeclock state, verify daily cleanup
7. Test `/ggp admin cache clear @user` command
8. Test `/ggp admin gc run` manual trigger

### Log Verification
Expected log patterns at INFO level:
```
INFO - Next database cleanup scheduled for 2026-04-24 06:00:00 (in 14.5 hours)
INFO - Starting daily database cleanup (06:00)...
INFO - GC: Removed 3 lunch timers from database
INFO - GC: Removed 5 timeclock state records  
INFO - GC: Token audit - 12 valid, 0 with warnings
INFO - Daily database cleanup completed
```

---

## Open Questions (Answer Before Implementation)

1. **Admin Access Control**: Should `/ggp admin` commands be restricted to specific users (e.g., via `ADMIN_SLACK_IDS` env var), or open to any linked user?

2. **GC Time**: Is 06:00 acceptable, or different time preferred (e.g., 03:00, 07:00)? Should it be configurable via env var?

3. **Token Age Warning**: Should weekly audit flag tokens older than X months (6? 12?) for review, or only report actual problems (expired, empty scopes)?

4. **Startup Validation**: Should bot run quick integrity check on all databases at startup and log summary (no action taken)?

5. **Scope Refresh Strategy**: When `get_token()` finds empty scopes, should it:
   - Log warning and return token (let API refresh on verify)
   - Log warning and trigger immediate scope refresh
   - Something else?

---

## Agent Context (For Future Sessions)

**Where We Left Off:**
- Comprehensive TOKEN AUDIT logging has been implemented and pushed (commit `081816e`)
- Database GC design is complete and documented in this file
- No implementation code written yet for GC scheduler or admin commands
- All syntax errors from earlier edits have been fixed
- Production bot is running with audit logging (but without GC)

**Next Immediate Actions:**
1. Create `src/ggp_bot/db_cleanup/scheduler.py` with `DatabaseCleanupScheduler` class
2. Modify `app.py` to start/stop scheduler alongside lunch_timer
3. Add lunch_timer and timeclock_state cleanup methods (DELETE ALL)
4. Add token audit method (report only)
5. Test on staging

**Key Implementation Pattern to Follow:**
Look at `src/ggp_bot/slack/lunch_timer.py`:
- Class with `__init__`, `start()`, `stop()` methods
- Global instance at bottom: `lunch_timer_manager = LunchTimerManager()`
- Async background task with `asyncio.sleep()` loop
- Start in `app.py:start_app()`, stop in `app.py:shutdown_app()`
- Use `try/except asyncio.CancelledError` for graceful shutdown

**Code Style Notes:**
- Use `logger.info()` for all GC operations
- Prefix audit logs with specific tokens: "GC:", "TOKEN AUDIT:", "ADMIN:"
- Follow existing exception handling patterns (sqlite3.Error, asyncio.CancelledError)
- Use type hints consistently
- Use f-strings for all string formatting

**Testing Environment:**
- Staging: Should have `DATA_DIR` set appropriately
- Can temporarily change 06:00 schedule to test sooner (e.g., 1 minute from now)
- Verify with: `sudo sqlite3 /var/lib/ggp-bot/*.db "SELECT COUNT(*) FROM ..."`

**Deployment Considerations:**
- No database schema changes needed (just DELETE operations)
- No environment variables required initially (hardcode 06:00, make configurable later)
- Safe to deploy - GC only removes data that should already be transient
- Monitor logs after first 06:00 run to verify counts look reasonable

---

## Related Documents

- `README.md` - User-facing docs (update with admin commands after Phase 3)
- `DEPLOY.md` - Production deployment guide (add GC behavior section)
- `implementation.md` - Technical architecture (reference for patterns)

---

**Ready for implementation once open questions are answered.**
