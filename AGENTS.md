# GGP Bot — Agent Context

## API Documentation

Scribe docs for the GGP Intranet API (the backend this bot consumes):
- **URL:** https://intranet.ggpsystems.co.uk/docs
- **Base URL:** https://intranet.ggpsystems.co.uk
- **API Version:** 1.0.1
- **Auth:** Bearer token per-user, obtained via `/api/auth/slack-link`

## Architecture

- **Slack bot** built with `slack-bolt` (async)
- **Intranet client** in `src/ggp_bot/intranet/client.py` — httpx-based, supports bot-token and per-user-token modes
- **Token storage** — encrypted SQLite via `src/ggp_bot/intranet/token_storage.py`
- **Commands** — single `/ggp` slash command with subcommands, dispatched in `src/ggp_bot/slack/handlers/commands.py`
- **Mentions** — natural-language intent matching in `src/ggp_bot/slack/handlers/mentions.py`

## Key Files

| File | Purpose |
|------|---------|
| `src/ggp_bot/intranet/client.py` | All API calls (25/25 endpoints implemented) |
| `src/ggp_bot/intranet/models.py` | Pydantic models for API responses |
| `src/ggp_bot/slack/handlers/commands.py` | Slash command dispatchers |
| `src/ggp_bot/slack/handlers/mentions.py` | @mention NL handlers |
| `src/ggp_bot/intranet/token_storage.py` | Encrypted token persistence |
| `GUIDE.md` | User-facing command reference |
