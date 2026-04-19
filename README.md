# ggp-bot

Slack bot for GGP intranet integration and Jenkins automation.

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

| Variable                         | Purpose                    | Source                 |
| -------------------------------- | -------------------------- | ---------------------- |
| `SLACK_BOT_TOKEN`                | Bot User OAuth Token       | Slack app settings     |
| `SLACK_SIGNING_SECRET`           | Request verification       | Slack app settings     |
| `SLACK_APP_TOKEN`                | Socket Mode connection     | Slack app-level tokens |
| `INTRANET_BASE_URL`              | Laravel API root           | Your infra             |
| `INTRANET_API_TOKEN`             | Bearer token for API       | Your infra             |
| `JENKINS_URL`                    | Jenkins root (future)      | Your infra             |
| `JENKINS_USER` / `JENKINS_TOKEN` | Jenkins API creds (future) | Your infra             |

## Project Structure

- `src/ggp_bot/slack/` — Bolt app, handlers, Socket Mode
- `src/ggp_bot/intranet/` — Laravel API client
- `src/ggp_bot/jenkins/` — Jenkins API client (future)

## Intranet API Notes

- Laravel 13 backend
- Token-based auth via `Authorization: Bearer <token>`
- Initial endpoints for testing: `/api/health-check` `/api/status` `/api/holidays/next-public`
