# ggp-bot

**Version:** 0.6.0  
**API Compatibility:** GGP Intranet API v0.99.6  

Slack bot for GGP intranet integration and Jenkins automation.

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

**Holiday command examples:**
- `/ggp holiday new 23/04/2026 Vacation` (single day)
- `/ggp holiday new 23/04/2026 25/04/2026 Family trip` (multi-day)
- `/ggp holiday new 23/04/2026 AM Doctor` (half day)
- `/ggp holiday cancel 123` (single cancellation)
- `/ggp holiday cancel 150-155` (range cancellation)
- `/ggp holiday cancel 150, 152-155, 158` (mixed cancellation)

Run `/ggp help holiday` for more details on date formats and cancellation syntax.

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

## Environment Variables

| Variable | Purpose | Source |
|----------|---------|--------|
| `SLACK_BOT_TOKEN` | Bot User OAuth Token (xoxb-) | Slack app settings → OAuth & Permissions |
| `SLACK_SIGNING_SECRET` | Request verification | Slack app settings → Basic Information |
| `SLACK_APP_TOKEN` | Socket Mode connection (xapp-) | Slack app settings → Basic Information → App-Level Tokens |
| `INTRANET_BASE_URL` | Laravel API root | `https://intranet.ggpsystems.co.uk` |
| `INTRANET_API_TOKEN` | Bearer token for API | Intranet admin / API team |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for user token encryption | Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
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
├── main.py              # Entry point
├── config.py            # Pydantic Settings
├── slack/
│   ├── app.py          # Bolt App with Socket Mode
│   └── handlers/
│       ├── commands.py  # Slash command handlers
│       └── __init__.py  # Handler exports
├── intranet/
│   ├── client.py       # HTTP client with Bearer auth
│   ├── models.py       # Pydantic response models
│   └── errors.py       # API-specific exceptions
└── jenkins/            # Jenkins integration (Phase 2 - future)
```

## Account Linking

Before using user-specific commands, you must link your Slack account:

1. Run `/ggp connect your.email@ggpsystems.co.uk yourpassword`
   - Passwords with spaces are supported
2. The bot will link your Slack ID to your intranet account
3. Now `/ggp whoami` and `/ggp holiday` commands will work

If you get `SLACK_USER_NOT_LINKED` error, run `/ggp connect` first.

## API Compatibility

The bot is aligned with **GGP Intranet API v0.99.6**:
- Health check: `GET /api/health` (no auth)
- Rate limits: `GET /api/rate-limits` (no auth)
- Next bank holiday: `GET /api/holidays/next-public` (no auth)
- Slack linking: `POST /api/auth/slack-link`
- User by Slack ID: `GET /api/users/by-slack-id/{slackId}`
- Holiday entitlement: `GET /api/holidays/entitlement` (pending)
- My holidays: `GET /api/holidays/mine` (pending)
- Request holiday: `POST /api/holidays/request` (pending)
- Cancel holiday: `DELETE /api/holidays/{id}` (pending)

See `/home/murrayc/c/ggp-intranet/API_BOT_DEVELOPER_GUIDE.md` for full API documentation.

## Version History

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

### Phase 3 ⏳ In Progress (Waiting on API)
- Holiday entitlement
- List holidays
- Book/cancel holidays

### Phase 4 ⏳ Planned
- User directory search
- Time clock integration

### Phase 5 ⏳ Future
- Jenkins CI/CD integration

## Support

For bot issues: Check logs and verify API connectivity with `/ggp status`

For API issues: See `API_BOT_DEVELOPER_GUIDE.md` in intranet project
