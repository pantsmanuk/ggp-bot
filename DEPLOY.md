# GGP Bot Deployment Guide

This guide covers deploying ggp-bot to Ubuntu 24.04 as a production systemd service.

## Prerequisites

### System Requirements
- Ubuntu 24.04 LTS (or compatible)
- Python 3.11 or higher
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
| `INTRANET_API_TOKEN` | Bearer token for API (bot-level, for public endpoints + linking) | Yes |

#### Security (Required for Production)
| Variable | Description | Required |
|----------|-------------|----------|
| `TOKEN_ENCRYPTION_KEY` | Fernet encryption key for user token storage. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | **Strongly Recommended** |

**Warning:** If `TOKEN_ENCRYPTION_KEY` is not set, the bot will derive a key from machine-specific data, making tokens only usable on that single machine. Always set this explicitly for production.

#### Production Configuration (Recommended)
| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |
| `LOG_FILE` | Path to log file (logs to console only if not set) | (unset) |
| `DATA_DIR` | Directory for SQLite databases (`tokens.db`, `lunch_timers.db`, `clock_state.db`) | `data` |

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
sudo chmod 755 /var/log/ggp-bot
```

## Step 3: Install Code

Clone the repository and set permissions:

```bash
cd /var/www/ggp-bot

# Clone as root (code should not be writable by runtime user)
sudo git clone https://github.com/pantsmanuk/ggp-bot.git .

# Set ownership: root owns code, ggp-bot group can read
sudo chown -R root:ggp-bot /var/www/ggp-bot
sudo chmod -R 750 /var/www/ggp-bot

# Ensure ggp-bot user can access .venv
sudo chown -R root:ggp-bot /var/www/ggp-bot/.venv
sudo chmod -R 750 /var/www/ggp-bot/.venv
```

## Step 4: Create Virtual Environment

Create a Python virtual environment for dependencies:

```bash
cd /var/www/ggp-bot

# Create venv
sudo python3 -m venv .venv

# Activate and install
source .venv/bin/activate
pip install -e .

# Ensure ggp-bot can read the venv
sudo chown -R root:ggp-bot .venv
sudo chmod -R 750 .venv
```

## Step 5: Configure Environment

Create the `.env` file with all required settings:

```bash
sudo tee /var/www/ggp-bot/.env > /dev/null << 'EOF'
# =============================================================================
# REQUIRED: Slack Bot Configuration
# =============================================================================
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_SIGNING_SECRET=your-signing-secret-here
SLACK_APP_TOKEN=xapp-your-app-level-token-here

# =============================================================================
# REQUIRED: Intranet API Configuration
# =============================================================================
# The bot uses two levels of authentication:
# 1. BOT TOKEN (INTRANET_API_TOKEN) - For public endpoints and account linking
# 2. USER TOKENS - Individual tokens stored per-user after /ggp connect
#
INTRANET_BASE_URL=https://intranet.ggpsystems.co.uk
INTRANET_API_TOKEN=your-bot-bearer-token-here

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
# Stores: tokens.db (encrypted user tokens), lunch_timers.db, clock_state.db
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
sudo systemctl status ggp-bot

# View logs
sudo tail -f /var/log/ggp-bot/ggp-bot.log
```

You should see output like:
```
INFO - Starting GGP Bot...
INFO - Signal handlers installed for SIGINT and SIGTERM
INFO - Starting Slack Socket Mode handler...
```

## Step 8: Test the Bot

In Slack, test basic functionality:

1. **Test connectivity:**
   ```
   /ggp ping
   ```
   Expected: "Pong! :table_tennis_paddle_and_ball: Bot is alive and responding."

2. **Test API status:**
   ```
   /ggp status
   ```
   Expected: Green checkmark with API version info

3. **Link an account:**
   ```
   /ggp connect your.email@ggpsystems.co.uk yourpassword
   ```
   Expected: "Account linked successfully!"

4. **Test private commands:**
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
sudo systemctl status ggp-bot
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
sudo systemctl status ggp-bot

# Check for Python errors in log
sudo grep -i error /var/log/ggp-bot/ggp-bot.log
```

## Updating the Bot

To update to a new version:

```bash
# 1. Stop the service
sudo systemctl stop ggp-bot

# 2. Navigate to code directory
cd /var/www/ggp-bot

# 3. Stash any local changes (if any)
sudo git stash -u

# 4. Pull latest changes
sudo git pull

# 5. Update dependencies (if pyproject.toml changed)
sudo /var/www/ggp-bot/.venv/bin/pip install -e .

# 6. Fix permissions after update
sudo chown -R root:ggp-bot /var/www/ggp-bot
sudo chmod -R 750 /var/www/ggp-bot
sudo chown -R root:ggp-bot /var/www/ggp-bot/.venv
sudo chmod -R 750 /var/www/ggp-bot/.venv

# 7. Start the service
sudo systemctl start ggp-bot

# 8. Verify it's running
sudo systemctl status ggp-bot
```

## Troubleshooting

### Service Won't Start

Check for configuration issues:

```bash
# Check systemd status for errors
sudo systemctl status ggp-bot

# Test running manually (as root, for debugging)
cd /var/www/ggp-bot
source .venv/bin/activate
ggp-bot
```

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

Check Slack app configuration:
1. Verify `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are correct
2. Ensure bot is invited to channels where commands are used
3. Check Slack app "Event Subscriptions" are enabled for slash commands

### Database Errors

Common database issues:

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

**Note:** Databases are created on first use. If you see "Permission denied" errors, ensure:
1. `/var/lib/ggp-bot` exists and is owned by `ggp-bot:ggp-bot`
2. The `DATA_DIR` env var matches this path
3. SELinux/AppArmor aren't blocking access (check `/var/log/audit/audit.log`)

## Security Notes

1. **Never run as root** - The service runs as dedicated `ggp-bot` user
2. **Protect `.env` file** - Contains secrets, readable only by root and ggp-bot group
3. **Code is not writable** - ggp-bot can read/execute but not modify code
4. **Data isolation** - All writable data is in `/var/lib/ggp-bot` and `/var/log/ggp-bot`
5. **Systemd hardening** - Service uses `NoNewPrivileges`, `ProtectSystem`, `ProtectHome`

## Backup Considerations

Important files and directories to backup:

```
/var/lib/ggp-bot/                  # DATA_DIR - All SQLite databases
├── tokens.db                       # Encrypted user tokens (CRITICAL)
├── lunch_timers.db                 # Active lunch timers
└── clock_state.db                # Clock state tracking for #Attendance

/var/www/ggp-bot/.env               # Configuration with secrets
/etc/systemd/system/ggp-bot.service # Service configuration (optional)
```

**Critical Notes:**
1. **`TOKEN_ENCRYPTION_KEY`** - If lost, all stored tokens become unusable and users must re-link accounts
2. **`DATA_DIR`** - Should be backed up regularly; contains all runtime state
3. **`.env file`** - Contains all secrets; store securely (e.g., encrypted password manager)

## Runtime Files Reference

The bot creates these files in `DATA_DIR` (default: `/var/lib/ggp-bot`):

| File | Purpose | Backup Priority |
|------|---------|-----------------|
| `tokens.db` | Encrypted user tokens (SQLite) | **CRITICAL** - Users must re-link if lost |
| `lunch_timers.db` | Active lunch break timers | Low - temporary state |
| `clock_state.db` | Time clock state tracking for #Attendance | Medium - prevents duplicate posts |

**Encryption:** `tokens.db` uses Fernet (AES-128) encryption. The `TOKEN_ENCRYPTION_KEY` is required to decrypt. Without it, the database is useless.

## Support

For issues:
1. Check logs: `sudo tail -f /var/log/ggp-bot/ggp-bot.log`
2. Test connectivity: `/ggp status` in Slack
3. Review this guide for common issues
4. Check `implementation.md` in repository for feature details
