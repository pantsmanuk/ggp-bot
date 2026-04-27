# ggp-bot

**Version:** 1.0.1  
**API Compatibility:** GGP Intranet API v1.0.0  
**Status:** ✅ Running in production

Slack bot for GGP intranet integration via slash commands and @mentions. Supports holidays, time clock, directory search, and natural language queries. Jenkins integration planned for v1.1.0.

## Key Features

- **Holiday Management** - Check balance, view bookings, request time off, and cancel (with batch/range support)
- **Time Clock** - Clock in/out with optional notes, view time cards, lunch timer with DM reminders
- **User Directory** - Search by name/email/department, view profiles
- **Natural Language** - Ask the bot questions conversationally via @mentions
- **Smart Suggestions** - Typo? The bot suggests the correct command
- **Secure** - User credentials encrypted with Fernet, per-user token storage

## Current Status

### ✅ Working Commands

All commands now use the consolidated `/ggp` interface:

| Command | Description | Auth Required |
|---------|-------------|---------------|
| `/ggp ping` | Test bot responsiveness | No |
| `/ggp status` | Check API health and version | No |
| `/ggp bank-holiday` | Show next UK bank holiday | No |
| `/ggp connect <email> <password>` | Link Slack to intranet account | No (with intranet creds) |
| `/ggp whoami` | Show your linked intranet profile | Yes |
| `/ggp help [command]` | Show help for all commands or specific topic | No |
| `/ggp holiday balance` | View holiday entitlement | Yes |
| `/ggp holiday list` | List your holiday bookings | Yes |
| `/ggp holiday new <dates>` | Request time off | Yes |
| `/ggp holiday cancel <id(s)>` | Cancel holiday(s) - supports single, multiple, or ranges | Yes |
| `/ggp whoami` | Show your linked intranet profile | Yes |
| `/ggp whois @<user>` | Show a user's profile and status | Yes |
| `/ggp directory search <query>` | Search directory by name/email/dept | Yes |
| `/ggp directory list` | List all users in directory | Yes |
| `/ggp clock in [note]` | Clock in (posts to #Attendance) | Yes |
| `/ggp clock out [note]` | Clock out (posts to #Attendance) | Yes |
| `/ggp clock lunch` | Start 1-hour lunch timer with DM reminders | Yes |
| `/ggp clock today` | Show today's time card | Yes |
| `/ggp clock week` | Show this week's time card | Yes |
| `/ggp clock` | Show current clock status | Yes |

**Holiday command examples:**
- `/ggp holiday new 23/04/2026 Vacation` (single day)
- `/ggp holiday new 23/04/2026 25/04/2026 Family trip` (multi-day)
- `/ggp holiday new 23/04/2026 AM Doctor` (half day)
- `/ggp holiday cancel 123` (single cancellation)
- `/ggp holiday cancel 150-155` (range cancellation)
- `/ggp holiday cancel 150, 152-155, 158` (mixed cancellation)

Run `/ggp help holiday` for more details on date formats and cancellation syntax.

### @Mention (Natural Language) Commands

You can also interact with the bot conversationally by mentioning it in any channel:

| Intent | Example |
|--------|---------|
| Show holidays | `@ggp-bot show my holidays` |
| Check holiday balance | `@ggp-bot what's my holiday balance?` |
| Clock status | `@ggp-bot am I clocked in?` |
| Find user info | `@ggp-bot who is @username?` |
| Show your profile | `@ggp-bot show my profile` |
| Search directory | `@ggp-bot find someone in engineering` |
| Next bank holiday | `@ggp-bot when is the next bank holiday?` |
| Get help | `@ggp-bot help` |

The bot understands natural language patterns - try asking questions naturally! If the bot doesn't understand, it will suggest using `/ggp help`.

### Special Features

**Lunch Timer** (`/ggp clock lunch`)
Starts a 1-hour timer. You'll receive DM reminders at 55, 59, and 60 minutes so you don't forget to clock back in.

**#Attendance Channel**
Clock in/out events are automatically posted to the #Attendance channel (configurable), showing who's in/out with optional notes. The bot tracks state to avoid duplicate posts.

## Development

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Run
cp .env.example .env
# ... edit .env with your tokens ...
ggp-bot
```

See [DEPLOY.md](DEPLOY.md) for production deployment instructions (systemd service on Ubuntu 24.04).

## Environment Variables

| Variable | Purpose | Source |
|----------|---------|--------|
| `SLACK_BOT_TOKEN` | Bot User OAuth Token (xoxb-) | Slack app settings → OAuth & Permissions |
| `SLACK_SIGNING_SECRET` | Request verification | Slack app settings → Basic Information |
| `SLACK_APP_TOKEN` | Socket Mode connection (xapp-) | Slack app settings → Basic Information → App-Level Tokens |
| `INTRANET_BASE_URL` | Laravel API root | `https://intranet.ggpsystems.co.uk` |
| `INTRANET_API_TOKEN` | Bearer token for API | Intranet admin / API team |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for user token encryption | Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `LOG_LEVEL` | Logging level | `INFO` (options: DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `LOG_FILE` | Optional file path for logs | e.g., `/var/log/ggp-bot/ggp-bot.log` (logs to console only if not set) |
| `DATA_DIR` | Directory for SQLite databases | e.g., `/var/lib/ggp-bot` or `data` for development |
| `JENKINS_URL` | Jenkins root (Phase 2) | Future |
| `JENKINS_USER` / `JENKINS_TOKEN` | Jenkins API creds (Phase 2) | Future |

**Slack Scopes Required:**
- `chat:write` - Send messages
- `commands` - Slash commands
- `app_mentions:read` - Respond to @mentions
- `users:read` - Look up user info
- `users:read.email` - Get user emails for linking

## Project Structure

```
src/ggp_bot/
├── main.py                  # Entry point with graceful shutdown
├── config.py                # Pydantic Settings
├── logging_config.py        # Structured logging
├── slack/
│   ├── app.py               # Bolt App with Socket Mode
│   ├── formatters.py        # Slack Block Kit builders
│   ├── lunch_timer.py       # Background lunch reminder service
│   └── handlers/
│       ├── commands.py      # Slash command handlers
│       ├── mentions.py      # @mention handlers
│       └── __init__.py      # Handler exports
├── intranet/
│   ├── client.py            # HTTP client with Bearer auth
│   ├── models.py            # Pydantic response models
│   ├── errors.py            # API-specific exceptions
│   ├── token_storage.py     # Encrypted per-user token storage
│   └── state_tracking.py    # Clock state tracking for #Attendance
├── jenkins/                 # Jenkins integration (Phase 2 - future)
│   ├── client.py
│   └── __init__.py
└── utils/
    └── date_parser.py       # UK date parsing (DD/MM/YYYY)
```

## Account Linking & Security

Before using user-specific commands, you must link your Slack account:

1. Run `/ggp connect your.email@ggpsystems.co.uk yourpassword`
   - Passwords with spaces are supported
2. The bot will link your Slack ID to your intranet account
3. Now `/ggp whoami` and `/ggp holiday` commands will work

If you get `SLACK_USER_NOT_LINKED` error, run `/ggp connect` first.

**Security Note:** User tokens are encrypted with Fernet (AES-128) and stored in a local SQLite database. The `TOKEN_ENCRYPTION_KEY` must be kept secure - if lost, stored tokens become unusable.

## API Compatibility

The bot is aligned with **GGP Intranet API v0.99.6**:
- Health check: `GET /api/health` (no auth)
- Rate limits: `GET /api/rate-limits` (no auth)
- Next bank holiday: `GET /api/holidays/next-public` (no auth)
- Slack linking: `POST /api/auth/slack-link`
- User by Slack ID: `GET /api/users/by-slack-id/{slackId}`
- Holiday entitlement: `GET /api/holidays/entitlement`
- My holidays: `GET /api/holidays/mine`
- Request holiday: `POST /api/holidays/request`
- Cancel holiday: `DELETE /api/holidays/{id}`
- Time clock status: `GET /api/timeclock/status`
- Time clock event: `POST /api/timeclock/event`
- Time clock today/week: `GET /api/timeclock/today`, `GET /api/timeclock/week`
- Directory search: `GET /api/users/search`

See the intranet API documentation at https://intranet.ggpsystems.co.uk/docs for full API reference.

## Version History

- **1.0.0** - Initial stable release: Complete Slack bot for GGP intranet integration with holiday management, time clock, directory search, natural language @mentions, admin tools, and secure encrypted token storage
- **0.6.0** - Consolidated slash commands into single `/ggp` interface with subcommands, added context-aware help and "did you mean?" suggestions
- **0.5.0** - Secure per-user token storage with SQLite + Fernet encryption, two-level authentication (bot + user tokens), improved scope-based error handling
- **0.3.3** - API v0.99.6 support: `/users/by-slack-id` endpoint, `SLACK_USER_NOT_LINKED` error handling
- **0.3.2** - Fix `/connect` command to support passwords with spaces
- **0.3.1** - Align with API v0.99.5: correct endpoints, models, error handling
- **0.3.0** - Phase 2 complete: Intranet client foundation with working endpoints
- **0.2.0** - Phase 1 complete: Slack app skeleton with Socket Mode
- **0.1.0** - Initial project skeleton

## Development Phases

### Phase 1 ✅ Complete
- Slack app with Socket Mode
- Basic connectivity (`/ggp ping`)

### Phase 2 ✅ Complete
- Intranet HTTP client
- Error handling
- Pydantic models
- Account linking (`/connect`)
- User identification (`/whoami` via Slack ID)
- Public endpoints (`/ggp status`, `/ggp bank-holiday`)

### Phase 3 ✅ Complete
- Holiday entitlement (`/ggp holiday balance`)
- List holidays (`/ggp holiday list`)
- Book holidays (`/ggp holiday new`)
- Cancel holidays with batch support (`/ggp holiday cancel`)

### Phase 4 ✅ Complete
- User directory search (`/ggp directory search`, `/ggp directory list`)
- User profile lookup (`/ggp whois @user`)
- Time clock integration with #Attendance posting
- Lunch timer with background reminders
- Natural language @mention handlers (8 intent patterns)

### Phase 5 ⏳ Future
- Jenkins CI/CD integration

## Support

For bot issues: Check logs and verify API connectivity with `/ggp status`

For API issues: See the API documentation at https://intranet.ggpsystems.co.uk/docs
