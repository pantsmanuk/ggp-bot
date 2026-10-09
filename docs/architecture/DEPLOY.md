# GGP Bot Deployment Guide

This guide covers installing and updating ggp-bot on Ubuntu 24.04 as a production systemd service.

For an existing installation, use [Updating the bot](#updating-the-bot). Run commands on the production host, not the development host. Stop if a command fails. Resolve the failure before continuing.

Use a Bash shell with access to the root-owned code directory. If your account cannot traverse `/var/www/ggp-bot`, open an administrative shell with `sudo -i`. Git commands run through `sudo` use root's Git configuration and credentials.

## Prerequisites

### System Requirements

- Ubuntu 24.04 LTS (or compatible)
- Python 3.11 or higher, with the matching `venv` package and pip support
- systemd
- Git

### Required Environment Variables

Before starting, obtain and configure these variables:

#### Slack (Required for Bot Operation)
| Variable | Source | Required |
|----------|--------|----------|
| `SLACK_BOT_TOKEN` | Slack app → OAuth & Permissions (starts with `xoxb-`) | Yes |
| `SLACK_SIGNING_SECRET` | Slack app → Basic Information | Yes |
| `SLACK_APP_TOKEN` | Slack app → Basic Information → App-Level Tokens (starts with `xapp-`) | Yes |

#### Intranet API (Required for Most Features)
| Variable | Description | Required |
|----------|-------------|----------|
| `INTRANET_BASE_URL` | Intranet API root URL (default: `https://intranet.ggpsystems.co.uk`) | Recommended |
| `INTRANET_API_TOKEN` | Optional bot-level Bearer token. User commands use tokens obtained through `/ggp connect`. | No |

#### Security (Required for Production)
| Variable | Description | Required |
|----------|-------------|----------|
| `TOKEN_ENCRYPTION_KEY` | Fernet encryption key for user token storage. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | **Required by this production guide** |

**Warning:** If `TOKEN_ENCRYPTION_KEY` is not set, the bot will derive a key from machine-specific data, making tokens only usable on that single machine. Always set this explicitly for production.

#### Production Configuration (Recommended)
| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |
| `LOG_FILE` | Path to log file (logs to console only if not set) | (unset) |
| `DATA_DIR` | Directory for SQLite databases (`tokens.db`, `lunch_timers.db`, `timeclock_state.db`) | `data` |

## Step 1: Create System User

Create a dedicated user for running the bot (do not run as root):

```bash
sudo useradd -r -s /bin/false -d /var/lib/ggp-bot -m ggp-bot
```

This creates:

- User `ggp-bot` with no login shell
- Home directory `/var/lib/ggp-bot` for data storage

## Step 2: Setup Directories

Create the required directory structure:

```bash
# Code directory
sudo mkdir -p /var/www/ggp-bot
sudo chown root:ggp-bot /var/www/ggp-bot
sudo chmod 750 /var/www/ggp-bot

# Data directory (already created by useradd, but ensure permissions)
sudo chown ggp-bot:ggp-bot /var/lib/ggp-bot
sudo chmod 750 /var/lib/ggp-bot

# Log directory
sudo mkdir -p /var/log/ggp-bot
sudo chown ggp-bot:ggp-bot /var/log/ggp-bot
sudo chmod 750 /var/log/ggp-bot
```

## Step 3: Install Code

Clone the repository and set permissions:

```bash
cd /var/www/ggp-bot

# Clone as root (code should not be writable by runtime user)
sudo git clone --branch main https://github.com/pantsmanuk/ggp-bot.git .

# Set ownership and preserve executable flags on scripts
sudo chown -R root:ggp-bot /var/www/ggp-bot
sudo chmod -R u=rwX,g=rX,o= /var/www/ggp-bot
```

## Step 4: Create Virtual Environment

Create a Python virtual environment for dependencies:

```bash
cd /var/www/ggp-bot

# Create venv
sudo python3 -m venv .venv

# Install into the root-owned venv explicitly
sudo .venv/bin/python -m pip install -e .

# Let the service user read libraries and execute entry points
sudo chown -R root:ggp-bot .venv
sudo chmod -R u=rwX,g=rX,o= .venv
```

## Step 5: Configure Environment

For a new installation, create the `.env` file with all required settings. Do not replace an existing production `.env` or regenerate its encryption key during an update.

Create the file with restricted permissions before writing its contents:

```bash
sudo install -o root -g ggp-bot -m 640 /dev/null /var/www/ggp-bot/.env
sudo tee /var/www/ggp-bot/.env > /dev/null << 'EOF'
# =============================================================================
# REQUIRED: Slack Bot Configuration
# =============================================================================
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_SIGNING_SECRET=your-signing-secret-here
SLACK_APP_TOKEN=xapp-your-app-level-token-here

# =============================================================================
# Intranet API Configuration
# =============================================================================
# The bot uses two levels of authentication:
# 1. OPTIONAL BOT TOKEN (INTRANET_API_TOKEN) - For bot-level requests
# 2. USER TOKENS - Individual tokens stored per-user after /ggp connect
#
INTRANET_BASE_URL=https://intranet.ggpsystems.co.uk
# INTRANET_API_TOKEN=your-bot-bearer-token-here

# =============================================================================
# REQUIRED: Token Encryption (CRITICAL for production)
# =============================================================================
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# KEEP THIS KEY SECRET AND BACKED UP! If lost, all stored user tokens become unusable.
TOKEN_ENCRYPTION_KEY=your-fernet-key-here

# =============================================================================
# RECOMMENDED: Production Logging Configuration
# =============================================================================
LOG_LEVEL=INFO
LOG_FILE=/var/log/ggp-bot/ggp-bot.log

# =============================================================================
# REQUIRED: Data Directory (must match Step 2 permissions)
# =============================================================================
# Stores: tokens.db (encrypted user tokens), lunch_timers.db, timeclock_state.db
DATA_DIR=/var/lib/ggp-bot
EOF

# Secure the .env file (contains secrets)
sudo chown root:ggp-bot /var/www/ggp-bot/.env
sudo chmod 640 /var/www/ggp-bot/.env
```

**Critical:** Replace all placeholder values with your actual tokens. The `TOKEN_ENCRYPTION_KEY` is particularly important - generate it once and store it securely (e.g., in your password manager).

## Step 6: Install Systemd Service

Copy the service file and enable it:

```bash
# Copy service file
sudo cp /var/www/ggp-bot/deploy/ggp-bot.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable ggp-bot
```

## Step 7: Start the Service

Start the bot and verify it's running:

```bash
# Start the service
sudo systemctl start ggp-bot

# Check status
sudo systemctl status ggp-bot --no-pager

# View logs
sudo tail -f /var/log/ggp-bot/ggp-bot.log
```

You should see output like:
```
INFO - Starting GGP Bot...
INFO - Starting Slack Socket Mode handler...
```

## Step 8: Test the Bot

In Slack, test basic functionality:

1. **Test connectivity.**
   ```
   /ggp ping
   ```
   Expected: "Pong! :table_tennis_paddle_and_ball: Bot is alive and responding."

2. **Test API status.**
   ```
   /ggp status
   ```
   Expected: Green checkmark with API version info

3. **Link an account.**
   ```
   /ggp connect your.email@ggpsystems.co.uk yourpassword
   ```
   Expected: "Account linked successfully!"

4. **Test private commands.**
   ```
   /ggp whoami
   ```
   Expected: Your profile information (only visible to you)

## Managing the Service

### Start/Stop/Restart

```bash
# Start
sudo systemctl start ggp-bot

# Stop
sudo systemctl stop ggp-bot

# Restart
sudo systemctl restart ggp-bot

# Check status
sudo systemctl status ggp-bot --no-pager
```

### View Logs

```bash
# Follow log file (real-time)
sudo tail -f /var/log/ggp-bot/ggp-bot.log

# View last 100 lines
sudo tail -n 100 /var/log/ggp-bot/ggp-bot.log

# View systemd journal
sudo journalctl -u ggp-bot -f
```

### Check for Errors

```bash
# Check if service is failing
sudo systemctl status ggp-bot --no-pager

# Check for Python errors in log
sudo grep -i error /var/log/ggp-bot/ggp-bot.log
```

## Updating the bot

This procedure assumes the service paths in `deploy/ggp-bot.service`. If production uses different paths, inspect `sudo systemctl cat ggp-bot` and use those paths throughout. File-log examples use this guide's `LOG_FILE`; the journal works regardless of that setting.

Use the same Bash session for all update and rollback steps. Record the previous commit and backup directory outside that session in case you disconnect. Do not stash production changes automatically, replace `.env`, change `TOKEN_ENCRYPTION_KEY`, or delete database files.

### 1. Check the installation before stopping the service

```bash
cd /var/www/ggp-bot
sudo git status --short
sudo git branch --show-current
sudo git rev-parse HEAD
sudo systemctl cat ggp-bot
sudo .venv/bin/python -c 'import json; from importlib.metadata import distribution; print(json.loads(distribution("ggp-bot").read_text("direct_url.json") or "{}").get("dir_info", {}).get("editable", False))'
```

Require a clean checkout, branch `main`, and editable result `True`. Review any local changes before proceeding. Ignored `.env` and `.venv` do not appear in Git status. If the installation is not editable, source changes alone will not update the installed package. Plan and test package reinstallation before continuing.

Fetch while the existing service is still running. Check that the update is a fast-forward and inspect changes that require extra deployment work:

```bash
sudo git fetch origin --prune
previous_revision=$(sudo git rev-parse HEAD)
target_revision=$(sudo git rev-parse origin/main)
sudo git merge-base --is-ancestor "$previous_revision" "$target_revision"
sudo git diff --stat "$previous_revision" "$target_revision"
sudo git diff "$previous_revision" "$target_revision" -- pyproject.toml uv.lock deploy/ggp-bot.service
printf 'Previous commit: %s\nTarget commit: %s\n' "$previous_revision" "$target_revision"
```

If the ancestry check fails, stop and resolve the branch divergence. Review release notes for database migrations or configuration changes before deploying. For dependency updates, test the resolved package versions in development before installing them in production. Pip does not use `uv.lock` automatically.

### 2. Stop the service and back up state

Back up the databases while the service is stopped so SQLite files and any journal files remain consistent. The backup contains secrets. Keep it root-only and copy it to your secured backup storage.

```bash
sudo systemctl stop ggp-bot
backup_dir="/var/backups/ggp-bot/$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -d -m 700 "$backup_dir"
sudo cp -a /var/lib/ggp-bot "$backup_dir/data"
sudo cp -a .env "$backup_dir/env"
sudo cp -a /etc/systemd/system/ggp-bot.service "$backup_dir/service"
printf '%s\n' "$previous_revision" | sudo tee "$backup_dir/revision" >/dev/null
printf 'Backup directory: %s\n' "$backup_dir"
```

Use the actual `DATA_DIR` if production differs. If dependencies or package installation will change, also save the virtual environment before changing it:

```bash
sudo cp -a .venv "$backup_dir/venv"
```

If backup fails, restart the unchanged service and resolve the failure before retrying.

### 3. Apply the reviewed source update

Fast-forward to the commit inspected in step 1. Using the recorded commit avoids fetching a newer, unreviewed release during downtime.

```bash
sudo git merge --ff-only "$target_revision"

# Update ownership of tracked files, excluding .env and .venv
sudo git ls-files -z | sudo xargs -0 -r chown root:ggp-bot
sudo git ls-files -z | sudo xargs -0 -r chmod u=rwX,g=rX,o=

# Make code directories traversable without touching Git metadata or the venv
sudo find . -path ./.git -prune -o -path ./.venv -prune -o -type d -exec chown root:ggp-bot {} + -exec chmod 750 {} +
```

For a source-only update in this editable installation, skip dependency installation. If package dependencies, entry points, or build configuration changed, use the tested installation procedure. For this guide's pip-managed environment:

```bash
sudo .venv/bin/python -m pip install -e .
sudo chown -R root:ggp-bot .venv
sudo chmod -R u=rwX,g=rX,o= .venv
sudo .venv/bin/python -m pip check
```

If the service file changed, review production overrides before replacing it, then reload systemd:

```bash
sudo install -o root -g root -m 644 deploy/ggp-bot.service /etc/systemd/system/ggp-bot.service
sudo systemctl daemon-reload
```

If any update command fails, do not continue to startup. Use the rollback procedure below.

### 4. Start and verify the bot

```bash
sudo systemctl start ggp-bot
sudo systemctl is-active --quiet ggp-bot
sudo systemctl status ggp-bot --no-pager
sudo git rev-parse HEAD
sudo journalctl -u ggp-bot --since "5 minutes ago" --no-pager
```

Require `HEAD` to equal the recorded target commit. Check logs for successful startup and new errors. An active process alone does not prove command handling works.

From an already linked account in Slack, run:

1. `/ggp ping` to verify command delivery and response.
2. `/ggp status` to verify intranet connectivity.
3. `/ggp whoami` to verify stored token access and user authentication.

Do not use clock-in, clock-out, or lunch commands solely to verify a deployment; they change attendance state. Do not re-link an existing account unless authentication requires it.

### Deploying the SQLite connection fix

Commit `d6acbf9`, merged in PR #37, closes connections explicitly. It changes no dependencies, database schema, encryption key, or service configuration. For this release, follow steps 1 through 4 and skip the optional package and service-file installation commands.

After the update, confirm the fix is included:

```bash
sudo git merge-base --is-ancestor d6acbf9 HEAD
```

Check logs immediately and again after several hours for `Too many open files`, `unable to open database file`, and command-listener failures. Old log entries remain; inspect timestamps after deployment. No database migration or restoration is needed for this fix.

### Roll back a failed update

Stop the service before changing code. If Git still points to the previous commit and no environment or service changes occurred, restart the previous service directly.

Otherwise, use the recorded previous commit and backup directory. If the session was lost, set `backup_dir` to the recorded path and recover `previous_revision` with `previous_revision=$(sudo cat "$backup_dir/revision")`:

```bash
cd /var/www/ggp-bot
sudo systemctl stop ggp-bot
sudo git status --short
sudo git switch --detach "$previous_revision"
```

Require a clean status before checkout; do not force checkout over local changes. After switching revisions, repeat the tracked-file and directory ownership commands from step 3. Detached checkout leaves `main` at the attempted release and runs the previous code without rewriting branch history.

If package installation changed, restore the saved virtual environment to its original path:

```bash
sudo mv .venv ".venv.failed-$(date -u +%Y%m%dT%H%M%SZ)"
sudo cp -a "$backup_dir/venv" .venv
```

If the systemd service file changed, restore it and reload systemd:

```bash
sudo cp -a "$backup_dir/service" /etc/systemd/system/ggp-bot.service
sudo systemctl daemon-reload
```

Keep the current `.env`, encryption key, and databases for source-only rollback. For a release with database migrations or configuration changes, follow that release's recovery instructions. Restoring a database backup discards changes made since the backup; do not do so automatically.

```bash
sudo systemctl start ggp-bot
sudo systemctl is-active --quiet ggp-bot
sudo systemctl status ggp-bot --no-pager
sudo journalctl -u ggp-bot --since "5 minutes ago" --no-pager
```

Repeat the Slack checks from step 4. Record that production is running the previous commit. Before retrying the release, complete preflight review while the previous code is running. Stop the service before switching back to `main`, because that branch still points to the attempted release. Apply the corrected update procedure before restarting.

## Troubleshooting

### Service Won't Start

Check for configuration issues:

```bash
# Check systemd status for errors
sudo systemctl status ggp-bot --no-pager

# Read startup failures under the actual service user and hardening settings
sudo journalctl -u ggp-bot -b -n 100 --no-pager
sudo systemctl cat ggp-bot
```

Use systemd for startup diagnostics. Do not launch another bot process manually or run the bot as root. That can create duplicate Slack sessions and incorrectly owned runtime files.

Common issues:

- Missing `.env` file or incorrect permissions
- Invalid tokens in `.env`
- Database directory not writable by ggp-bot user

### Permission Denied Errors

```bash
# Check file ownership
ls -la /var/www/ggp-bot/.env
ls -la /var/lib/ggp-bot
ls -la /var/log/ggp-bot/

# Fix if needed
sudo chown root:ggp-bot /var/www/ggp-bot/.env
sudo chmod 640 /var/www/ggp-bot/.env
sudo chown -R ggp-bot:ggp-bot /var/lib/ggp-bot
sudo chown -R ggp-bot:ggp-bot /var/log/ggp-bot
```

### Bot Connects But Doesn't Respond to Commands

Check recent service logs first. A database-opening failure or `Too many open files` can leave the process running while commands fail. See [Database errors](#database-errors).

If logs show Slack configuration failures:

1. Verify `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are correct.
2. Verify Socket Mode is enabled and the app-level token has `connections:write`.
3. Verify `/ggp` is configured under Slack's Slash Commands and the app is installed in the workspace.

Event Subscriptions control events such as app mentions. They do not enable slash commands.

### Database Errors

Inspect recent logs before changing permissions. `unable to open database file` can indicate file-descriptor exhaustion as well as a path or permission problem. If logs also show `Too many open files`, deploy the connection fix above. Restarting releases handles but does not fix leaking connections.

To inspect a running process before restarting it:

```bash
bot_pid=$(sudo systemctl show ggp-bot -p MainPID --value)
# Continue only if MainPID is nonzero and the process still exists
sudo ls -l "/proc/$bot_pid/fd"
sudo cat "/proc/$bot_pid/limits"
```

For confirmed permission problems, check the actual configured data directory:

```bash
# Check database permissions
ls -la /var/lib/ggp-bot/

# Should be owned by ggp-bot user
cd /var/lib/ggp-bot
sudo chown ggp-bot:ggp-bot *.db
sudo chmod 660 *.db

# Check directory permissions
ls -ld /var/lib/ggp-bot
# Should be: drwxr-x--- ggp-bot ggp-bot
```

**Note:** Databases are initialized at startup. If you see "Permission denied" errors, ensure:

1. `/var/lib/ggp-bot` exists and is owned by `ggp-bot:ggp-bot`
2. The `DATA_DIR` env var matches this path
3. The service's `ReadWritePaths` includes that directory. Check the journal for AppArmor or other access-denial messages.

## Security Notes

1. **Never run as root** - The service runs as dedicated `ggp-bot` user
2. **Protect `.env` file** - Contains secrets, readable only by root and ggp-bot group
3. **Code is not writable** - ggp-bot can read/execute but not modify code
4. **Data isolation** - All writable data is in `/var/lib/ggp-bot` and `/var/log/ggp-bot`
5. **Systemd hardening** - Service uses `NoNewPrivileges`, `ProtectSystem`, `ProtectHome`

## Backup Considerations

Stop the service before copying SQLite files, or use SQLite's online backup API. Do not copy only the main database files while writes are in progress. Include the encryption key with the secured backup.

Important files and directories to backup:

```
/var/lib/ggp-bot/                  # DATA_DIR - All SQLite databases
├── tokens.db                     # Encrypted user tokens (CRITICAL)
├── lunch_timers.db               # Active lunch timers
└── timeclock_state.db            # Clock state tracking for #Attendance

/var/www/ggp-bot/.env               # Configuration with secrets
/etc/systemd/system/ggp-bot.service # Service configuration (optional)
```

**Critical Notes:**

1. **`TOKEN_ENCRYPTION_KEY`** - If lost, all stored tokens become unusable and users must re-link accounts
2. **`DATA_DIR`** - Should be backed up regularly; contains all runtime state
3. **`.env file`** - Contains all secrets; store securely (e.g., encrypted password manager)

## Runtime Files Reference

The bot creates these files in `DATA_DIR`. The application default is `data` relative to its working directory; this guide sets `/var/lib/ggp-bot`:

| File | Purpose | Backup Priority |
|------|---------|-----------------|
| `tokens.db` | Encrypted user tokens (SQLite) | **CRITICAL** - Users must re-link if lost |
| `lunch_timers.db` | Active lunch break timers | Low - temporary state |
| `timeclock_state.db` | Time clock state tracking for #Attendance | Medium - prevents duplicate posts |

**Encryption:** `tokens.db` uses Fernet (AES-128) encryption. The `TOKEN_ENCRYPTION_KEY` is required to decrypt. Without it, the database is useless.

## Support

For issues:

1. Check logs: `sudo tail -f /var/log/ggp-bot/ggp-bot.log`
2. Test connectivity: `/ggp status` in Slack
3. Review this guide for common issues
4. Check the [user guide](../user/GUIDE.md) for command details
