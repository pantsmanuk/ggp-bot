# GGP Bot User Guide

Welcome to GGP Bot! This guide will help you get the most out of your Slack-integrated intranet assistant.

---

## Getting Started

### Linking Your Account

Before you can use personalized commands, you need to connect your Slack account to the company intranet:

```Slack
/ggp connect <your-intranet-email> <your-password>
```

**Example:**
```Slack
/ggp connect john.doe@ggpsystems.co.uk mypassword
```

> **Note:** Once linked, your authentication is saved securely. You won't need to connect again unless your session expires.

---

## Commands Available to Everyone

These commands work without connecting your account:

### Check Bot Status
```Slack
/ggp ping
```
Tests if the bot is responding. You'll receive a "Pong!" response if everything is working.

### Check Intranet Status
```Slack
/ggp status
```
Shows the current health and version of the intranet API.

### Next Bank Holiday
```Slack
/ggp bank-holiday
```
Displays the next UK bank holiday, including how many days until it arrives.

### Get Help
```Slack
/ggp help
/ggp help <command>
```
Shows available commands. Add a command name for detailed help on that specific command.

**Examples:**
```Slack
/ggp help holiday
/ggp help clock in
/ggp help directory search
```

---

## Commands Requiring Account Connection

Once you've linked your account with `/ggp connect`, these commands become available:

### Clock Commands (Time Tracking)

#### Clock In
```Slack
/ggp clock in [note]
```

**Simple clock in:**
```Slack
/ggp clock in
```

**With a note:**
```Slack
/ggp clock in Working on Project X
```

> **Note:** When you clock in, a message is posted to the #Attendance channel (only on state change).

#### Clock Out
```Slack
/ggp clock out [note]
```

**Simple clock out:**
```Slack
/ggp clock out
```

**With a note:**
```Slack
/ggp clock out Ending shift
```

> **Note:** Clocking out also posts to the #Attendance channel.

#### Start Lunch Timer
```Slack
/ggp clock lunch
```
Starts a 1-hour lunch break with automatic reminders:
- **5 minutes left:** Reminder that lunch is almost over
- **1 minute left:** Final warning before lunch ends
- **Lunch over:** Prompt to clock back in

> **Tips:**
>
> - If you clock in early with `/ggp clock in`, any remaining reminders are automatically cancelled
> - Calling `/ggp clock lunch` multiple times does nothing,  it's safe to accidentally repeat

#### Check Clock Status
```Slack
/ggp clock
```
Shows your current clock status:
- Whether you're clocked in or out
- When you last clocked in/out
- Current session duration
- Whether you're on lunch break

#### View Today's Time Card
```Slack
/ggp clock today
```
Shows all your clock events for today with times and durations.

#### View This Week's Time Card
```Slack
/ggp clock week
```
Shows all your clock events for the current week, grouped by day.

---

### Directory Commands

#### Search the Directory
```Slack
/ggp directory search <query>
```

**Search by name:**
```Slack
/ggp directory search john
```

**Search by department:**
```Slack
/ggp directory search engineering
```

**Search by email:**

```Slack
/ggp directory search john@company.com
```

Results include name, email, department, and job title (up to 20 results shown).

#### List All Users
```Slack
/ggp directory list
```
Shows all users in the company directory (first 30 users displayed). Use search for more specific results.

---

### Holiday Commands

#### Check Holiday Balance
```Slack
/ggp holiday balance
```
Shows your current holiday entitlement:
- Total days allocated
- Days already used
- Days remaining
- Pending requests
- Company year dates

#### List Your Holidays
```Slack
/ggp holiday list
```
Displays all your holiday bookings with:
- Request ID numbers
- Dates (including half-day markers)
- Number of working days
- Approval status
- Any notes you added

> **Tip:** Note the request IDs - you'll need them to cancel holidays.

#### Request Time Off
```Slack
/ggp holiday new <dates> [note]
```

**Single day:**
```Slack
/ggp holiday new 23/04/2026 Family vacation
```

**Multiple days:**
```Slack
/ggp holiday new 23/04/2026 25/04/2026 Family trip
```

**Half day (morning):**
```Slack
/ggp holiday new 23/04/2026 AM Doctor appointment
```

**Half day (afternoon):**
```Slack
/ggp holiday new 23/04/2026 PM Dental checkup
```

**Date formats accepted:**
- `2026-04-23` (ISO format)
- `23/04/2026` or `23-04-2026` (UK format)
- `23 Apr 2026` (verbose format)

#### Cancel Holiday Requests
```Slack
/ggp holiday cancel <id(s)>
```

**Single holiday:**
```Slack
/ggp holiday cancel 123
```

**Multiple holidays:**
```Slack
/ggp holiday cancel 123, 125, 127
```

**Range of holidays:**

```Slack
/ggp holiday cancel 150-155
```

**Mixed:**
```Slack
/ggp holiday cancel 150, 152-155, 158
```

> **Tip:** Use `/ggp holiday list` first to find the holiday IDs you want to cancel.

---

### Profile Commands

#### View Your Profile
```Slack
/ggp whoami
```
Displays your linked intranet profile including:
- Name and email
- Department and job title
- Phone number and location
- Slack link status

#### View Another User's Profile
```Slack
/ggp whois <@user>
```
**Example:**
```Slack
/ggp whois @john.doe
```

Shows a colleague's profile and current status (working, clocked in, on holiday, etc.).

> **Tip:** Type `@` and select the user from Slack's autocomplete to ensure proper linking.

---

## Talking to the Bot (@mentions)

You can also interact with GGP Bot by mentioning it in a channel. The bot somewhat understands natural language patterns. GGP Bot is in #attendance and #autobuild.

> **Privacy Note:** @mention responses are visible to everyone in the channel. For sensitive information, use slash commands (only you see the response).

### What You Can Ask via @mention

**Bank holidays:**

- `@ggp-bot next public holiday`
- `@ggp-bot when's the next bank holiday?`

**Clock status:**

- `@ggp-bot am I clocked in?`
- `@ggp-bot show my status`

**Directory search:**

- `@ggp-bot find john`
- `@ggp-bot search engineering`
- `@ggp-bot who works in sales?`

**Holiday queries:**

- `@ggp-bot show my holidays`
- `@ggp-bot what's my holiday balance?`
- `@ggp-bot how many holidays do I have left?`

**People lookup:**

- `@ggp-bot who is @john.doe?`
- `@ggp-bot tell me about @jane.smith`

**Getting help:**

- `@ggp-bot help`
- `@ggp-bot what can you do?`

---

## Tips & Best Practices

### Privacy
- **Slash commands** (`/ggp ...`) are private - only you see the response
- **@mentions** are public - everyone in the channel can see the response

Use slash commands for:
- Booking or canceling holidays
- Clocking in/out
- Viewing detailed time cards
- Viewing your full profile

Use @mentions for:
- Quick questions
- When you want to share information with the channel

### Quick Reference

| Command | Purpose | Auth Required |
|---------|---------|---------------|
| `/ggp ping` | Test bot is working | No |
| `/ggp status` | Check intranet health | No |
| `/ggp bank-holiday` | Next UK bank holiday | No |
| `/ggp connect` | Link your account | No |
| `/ggp clock in` | Clock in | Yes |
| `/ggp clock out` | Clock out | Yes |
| `/ggp clock lunch` | Start lunch timer | Yes |
| `/ggp clock` | Current status | Yes |
| `/ggp clock today` | Today's time card | Yes |
| `/ggp clock week` | Week's time card | Yes |
| `/ggp directory search` | Find people | Yes |
| `/ggp directory list` | All users | Yes |
| `/ggp holiday balance` | Check entitlement | Yes |
| `/ggp holiday list` | View bookings | Yes |
| `/ggp holiday new` | Request time off | Yes |
| `/ggp holiday cancel` | Cancel booking | Yes |
| `/ggp whoami` | Your profile | Yes |
| `/ggp whois @user` | Someone's profile | Yes |
| `/ggp admin refresh @user` | Refresh user's API token (admin only) | Yes |

---

## Need Help?

- Use `/ggp help` to see all available commands
- Use `/ggp help <command>` for detailed help on a specific command
- Mention `@ggp-bot help` in any channel for assistance

If you encounter issues or have questions, please contact your system administrator.

---

*GGP Bot v1.0.0 - Making your work life easier, one command at a time.*