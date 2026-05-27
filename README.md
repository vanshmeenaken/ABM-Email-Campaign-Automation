# Ken Research — Satellite Account Email Sender

Send test emails through 4 satellite accounts via Claude Code (VS Code).

---

## Quick Start

1. Open this folder in VS Code
2. Open Claude Code (Command Palette → "Claude Code")
3. Type: `Send a test email from Alina to my.email@kenresearch.com`

That's it. The agent will handle the rest.

---

## How to Use

**Send from a specific account:**
```
Send from Alina to team@kenresearch.com
Send from Archita to john@kenresearch.com
Send from Sneha to marketing@kenresearch.com
Send from Tanushree to support@kenresearch.com
```

**With custom subject:**
```
Send from account 1 to team@kenresearch.com with subject "Hello Team"
```

**With custom body:**
```
Send from Alina to test@example.com with subject "Test" and body "This is a test message"
```

**Test all accounts:**
```
Send test emails from all 4 accounts to my.email@kenresearch.com
```

---

## Accounts

| # | Name | Status |
|---|------|--------|
| 1 | Alina Khan (ABM) | ✅ Ready |
| 2 | Archita Singh (ABM) | ✅ Ready |
| 3 | Sneha Malhotra (ABM) | ✅ Ready |
| 4 | Tanushree Kalita (ABM) | ✅ Ready |

---

## Files

- **CLAUDE.md** — Agent instructions (read this first)
- **send_email.py** — Python script that sends emails
- **README.md** — This file

---

## Setup

Before using, update the email addresses in `send_email.py`:

```python
ACCOUNTS = {
    "1": {
        "email": "alina.khan@kenresearch.com"      # ← UPDATE
    },
    "2": {
        "email": "archita.singh@kenresearch.com"   # ← UPDATE
    },
    "3": {
        "email": "sneha.malhotra@kenresearch.com"  # ← UPDATE
    },
    "4": {
        "email": "tanushree.kalita@kenresearch.com" # ← UPDATE
    }
}
```

Then just talk to Claude Code — the agent knows everything.

---

## Requirements

- Python 3.x
- `requests` library: `pip install requests`
- VS Code with Claude Code extension

---

## Questions?

Just ask the agent. It has all the context and can help with anything email-related for these 4 accounts.
