# ggp-bot Implementation Plan

## Project Overview

A modern Slack bot interfacing with the GGP intranet (Laravel 13) via Socket Mode, supporting both slash commands and conversational @mentions. Phase 1 focuses on intranet integration (holidays, directory, time clock). Phase 2 (future) will add Jenkins CI/CD capabilities.

---

## Architecture

```
src/ggp_bot/
├── main.py                    # Entry point + app initialization
├── config.py                  # Pydantic Settings (env vars)
├── errors.py                  # Custom exceptions
├── logging_config.py          # Structured logging
│
├── slack/
│   ├── app.py                 # Bolt App (Socket Mode)
│   ├── handlers/
│   │   ├── commands.py        # Slash command handlers
│   │   └── mentions.py        # @mention handlers (supports @ggp-bot AND @ggpbot)
│   └── formatters.py          # Slack Block Kit builders
│
├── intranet/
│   ├── client.py              # httpx wrapper with Bearer auth
│   ├── errors.py              # API-specific exceptions
│   ├── models.py              # Pydantic response models
│   └── endpoints/
│       ├── health.py          # /health, /rate-limits
│       ├── auth.py            # /auth/verify (token validation)
│       ├── holidays.py        # Full holiday CRUD
│       ├── users.py           # User profile, search, status
│       └── directory.py       # Phone directory
│
└── utils/
    └── date_helpers.py        # UK date parsing (DD/MM/YYYY)
```

---

## Dependencies

```toml
[project]
dependencies = [
    "slack-bolt>=1.20",
    "python-dotenv>=1.0",
    "httpx>=0.27",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]
```

---

## Environment Variables

```bash
# Slack (to be configured in future session)
SLACK_BOT_TOKEN=xoxb-...           # Bot User OAuth Token
SLACK_SIGNING_SECRET=...            # Request verification
SLACK_APP_TOKEN=xapp-...            # Socket Mode connection

# Intranet (token available when you have access)
INTRANET_BASE_URL=https://intranet.ggpsystems.co.uk/api
INTRANET_API_TOKEN=...              # Sanctum Bearer token

# Bot
LOG_LEVEL=INFO
```

---

## Bot Identity

- **Primary handle**: `@ggp-bot`
- **Alias handle**: `@ggpbot` (intranet currently uses this for notifications)
- **Display name**: `GGP Bot`
- **Supported contexts**: DMs (Phase 1), channels including #attendance (Phase 2)

---

## Implementation Sprints

### Sprint 1: Core Setup

**Goal**: Bot connects to Slack, responds to basic `/ping` command

| Task | File(s) | Acceptance Criteria |
|------|---------|---------------------|
| 1.1 Add pydantic-settings to deps | `pyproject.toml` | `pip install -e .` succeeds |
| 1.2 Create Settings config | `config.py` | Validates all env vars on startup |
| 1.3 Setup logging | `logging_config.py` | JSON-structured logs to stdout |
| 1.4 Define exceptions | `errors.py` | Hierarchy: `GgpBotError` -> specific |
| 1.5 Create Bolt app | `slack/app.py` | Socket Mode connection ready |
| 1.6 Implement `/ping` | `slack/handlers/commands.py` | Responds "Pong! Bot is alive" |
| 1.7 Wire up main.py | `main.py` | `ggp-bot` CLI command runs |
| 1.8 Create systemd unit | `deploy/ggp-bot.service` | Ready for Ubuntu 24.04 |

---

### Sprint 2: Intranet Client Foundation

**Goal**: Bot can talk to intranet API with proper auth & error handling

| Task | File(s) | Acceptance Criteria |
|------|---------|---------------------|
| 2.1 IntranetClient class | `intranet/client.py` | Async httpx client with Bearer auth |
| 2.2 Response envelope handling | `intranet/client.py` | Parses `{success, data, message, meta}` |
| 2.3 Rate limit tracking | `intranet/client.py` | Reads `X-RateLimit-*` headers |
| 2.4 Pydantic models | `intranet/models.py` | Models for Health, User, Absence |
| 2.5 Health endpoint | `intranet/endpoints/health.py` | `GET /health` + `GET /rate-limits` |
| 2.6 Error mapping | `intranet/errors.py` | Specific exceptions per error code |
| 2.7 Implement `/ggp status` | `slack/handlers/commands.py` | Reports API connectivity + version |
| 2.8 Integration test | `tests/integration/` | Real API call to `/health` passes |

**Error Code Mapping**:

| Intranet Code | Exception | Slack Message |
|---------------|-----------|---------------|
| `UNAUTHORIZED` | `IntranetAuthError` | "Cannot connect to intranet - authentication failed" |
| `INSUFFICIENT_SCOPE` | `IntranetScopeError` | "Bot lacks permission: {scope}" |
| `RATE_LIMIT_EXCEEDED` | `IntranetRateLimitError` | "Rate limit hit. Wait {seconds}s" |
| `VALIDATION_ERROR` | `IntranetValidationError` | "{message}" |
| `NOT_FOUND` | `IntranetNotFoundError` | "Not found: {resource}" |

---

### Sprint 3: Holidays MVP (PRIORITY)

**Goal**: Full holiday functionality (read + write) via slash commands and @mentions

| Task | File(s) | Acceptance Criteria |
|------|---------|---------------------|
| 3.1 Holiday endpoints | `intranet/endpoints/holidays.py` | All 7 holiday endpoints implemented |
| 3.2 Date parsing utils | `utils/date_helpers.py` | UK format (DD/MM/YYYY) -> ISO |
| 3.3 `/ggp holiday balance` | `slack/handlers/commands.py` | Shows entitlement summary |
| 3.4 `/ggp holiday list` | `slack/handlers/commands.py` | Lists user's holidays (Block Kit) |
| 3.5 `/ggp holiday new` | `slack/handlers/commands.py` | Parses: `/ggp holiday new 01/05/2026 for 3 days` |
| 3.6 `/ggp holiday cancel` | `slack/handlers/commands.py` | Cancels by ID |
| 3.7 Message formatters | `slack/formatters.py` | Rich Block Kit messages for holidays |
| 3.8 @mention handler | `slack/handlers/mentions.py` | Responds to "@ggp-bot show my holidays" |
| 3.9 Alias support | `slack/app.py` | Handles both @ggp-bot and @ggpbot |
| 3.10 Integration tests | `tests/integration/test_holidays.py` | Full CRUD flow with real API |

**Slash Commands**:

```
/ggp holiday balance
-> Shows: Total: 25, Used: 10, Remaining: 15, Pending: 2

/ggp holiday list
-> Shows: List of holidays with status (pending/approved)

/ggp holiday new 01/05/2026 for 3 days
-> Books 3 days from May 1st 2026

/ggp holiday new 01/05/2026 to 05/05/2026 "Summer break"
-> Date range with note

/ggp holiday cancel 123
-> Cancels holiday ID 123
```

**@mention Seeds** (conversational):

```
@ggp-bot show my holiday balance
@ggp-bot what holidays do I have booked?
@ggp-bot book holiday starting 01/05/2026 for 3 days
@ggp-bot book me off 01/05/2026 to 05/05/2026
@ggp-bot cancel holiday 123
@ggpbot next bank holiday
```

---

### Sprint 4: User Directory & Status ✅ Complete (v1.0.0)

**Goal**: Directory lookups and user status queries

| Task | File(s) | Status |
|------|---------|--------|
| 4.1 User endpoints | `intranet/client.py` | ✅ GET /users/by-slack-id/{id} |
| 4.2 Directory endpoint | `intranet/client.py` | ✅ GET /users/search |
| 4.3 `/ggp whois @user` | `slack/handlers/commands.py` | ✅ Shows profile + status |
| 4.4 `/ggp directory search <query>` | `slack/handlers/commands.py` | ✅ Searches by name/email/dept |
| 4.5 `/ggp directory list` | `slack/handlers/commands.py` | ✅ Lists all users |
| 4.6 User formatters | `slack/formatters.py` | ✅ Profile display |
| 4.7 @mention handlers | `slack/handlers/mentions.py` | ⏳ v1.0.0 - Natural language processing |

### Sprint 4b: Natural Language @mentions ⏳ v1.0.0

**Goal**: Conversational interactions via @mentions

| Task | File(s) | Status |
|------|---------|--------|
| 4b.1 Intent parsing | `slack/handlers/mentions.py` | ⏳ Pattern matching for intents |
| 4b.2 Holiday queries | `slack/handlers/mentions.py` | ⏳ "@ggp-bot show my holidays" |
| 4b.3 Directory queries | `slack/handlers/mentions.py` | ⏳ "@ggp-bot who is @user" |
| 4b.4 Clock queries | `slack/handlers/mentions.py` | ⏳ "@ggp-bot am I clocked in?" |
| 4b.5 Help/fallback | `slack/handlers/mentions.py` | ⏳ Unknown intent handling |

---

### Sprint 5: Time Clock ✅ Complete (v1.0.0)

**Goal**: Time clock operations with #Attendance integration

| Task | File(s) | Status |
|------|---------|--------|
| 5.1 Time clock endpoints | `intranet/client.py` | ✅ POST /timeclock/event, GET /timeclock/status |
| 5.2 Clock in/out | `slack/handlers/commands.py` | ✅ `/ggp clock in`, `/ggp clock out` with notes |
| 5.3 Status & history | `slack/handlers/commands.py` | ✅ `/ggp clock`, `/ggp clock today`, `/ggp clock week` |
| 5.4 #Attendance posting | `slack/handlers/commands.py` | ✅ Posts on state change only |
| 5.5 Lunch timer | `slack/lunch_timer.py` | ✅ 1-hour timer with DM reminders at 55/59/60 min |
| 5.6 State tracking | `intranet/state_tracking.py` | ✅ Prevents duplicate #Attendance posts |

### Sprint 6: Jenkins CI/CD ⏳ v1.1.0

**Goal**: Jenkins integration for build/deployment operations

**Status**: Deferred until bot is stable in production
**Rationale**: Want production use and stability before adding Jenkins automation

---

### Sprint 6: Production Readiness ✅ Complete (v1.0.0)

**Goal**: systemd service, graceful shutdown, comprehensive error handling

| Task | File(s) | Status |
|------|---------|--------|
| 6.1 Signal handling | `main.py` | ✅ SIGTERM graceful shutdown |
| 6.2 Graceful shutdown | `slack/app.py` | ✅ Lunch timer cleanup on exit |
| 6.3 systemd service | `deploy/ggp-bot.service` | ✅ Ubuntu 24.04 service unit |
| 6.4 Deployment docs | `DEPLOY.md` | ⏳ Step-by-step setup guide |
| 6.5 Integration tests | `tests/integration/` | ⏳ Holiday + clock tests |

---

## Release Roadmap

### v1.0.0 ✅ DEPLOYED TO PRODUCTION
**Status**: Feature complete and running in production

**Features delivered**:
- ✅ Consolidated slash commands (`/ggp` interface)
- ✅ Holiday management (balance, list, book, cancel)
- ✅ User directory search (`/ggp whois`, `/ggp directory`)
- ✅ Time clock integration with #Attendance posting
- ✅ Lunch timer with background reminders
- ✅ Natural language @mention handlers
- ✅ systemd service for production deployment
- ✅ Configurable file logging
- ✅ Secure per-user token storage

**Optional remaining**:
- ⏳ DEPLOY.md documentation (operational notes)
- ⏳ Expanded integration tests

### v1.1.0 (Future)
**Focus**: Jenkins CI/CD integration (Sprint 7)

---

## Testing Strategy

### Integration Tests (Primary)

```bash
# Run all integration tests (requires real intranet)
pytest -m integration

# Run specific suite
pytest tests/integration/test_holidays.py -v
```

### Manual Testing

```bash
# 1. Install
pip install -e .

# 2. Configure (when you have tokens)
cp .env.example .env
# ... edit .env ...

# 3. Run
ggp-bot

# 4. Test in Slack
/ggp ping
/ggp status
```

---

## Key Decisions

| Aspect | Decision |
|--------|----------|
| **Date Format** | UK format (DD/MM/YYYY) for user input |
| **Bot Handles** | `@ggp-bot` (primary) + `@ggpbot` (alias for migration) |
| **Interaction Modes** | Slash commands + @mentions (both from start) |
| **Error Transparency** | Specific, detailed error messages (dev-friendly) |
| **Testing** | Integration tests against real intranet API |
| **Deployment** | systemd service on Ubuntu 24.04 |
| **Contexts** | DMs initially, channels (including #attendance) in Phase 2 |
| **Phase 2 Scope** | Jenkins integration (deferred until Phase 1 stable) |

---

## Prerequisites for Sprint 1

- [ ] Slack app created with Bot Token, Signing Secret, App Token
- [ ] Intranet API token in `.env`
- [ ] This plan reviewed and confirmed

---

## Next Steps

1. Set up Slack app (when ready), obtain intranet API token
2. Begin Sprint 1 implementation
3. Sprint-by-sprint delivery with integration testing
