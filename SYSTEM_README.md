# Ken Research - Campaign Email Sender System

Complete satellite outreach campaign platform with threading, rate limiting, and real-time monitoring.

---

## 📋 Quick Start

### 1. Create a Campaign

```bash
python campaign_manager.py create
```

**Follow prompts:**
- Campaign name (e.g., "Q2 ABM Outreach")
- Account: 1=Alina, 2=Archita, 3=Sneha, 4=Tanushree
- Recipient list (one email per line)
- Email sequences (3-4 emails with subject/body and delay days)

**Output:** Campaign folder created in `campaigns/campaign_YYYYMMDD_HHMMSS/`

### 2. Run Campaign

```bash
python scheduler.py campaign_001
```

- Sends emails at 4-5 minute random intervals
- Threads follow-ups to previous emails (via inReplyTo)
- Max 2 retries on failure
- Updates progress in real-time

### 3. Monitor Progress

```bash
python dashboard.py
```

Open http://localhost:5000 to see:
- All campaigns + status
- Sent/Pending/Failed counts
- Real-time progress bars
- Email sequence step tracking

---

## 📁 Campaign Folder Structure

```
campaigns/
├── campaign_20260506_153000/
│   ├── brief.json           # Campaign metadata + email sequences
│   ├── recipients.csv       # Recipient email list
│   ├── progress.json        # Real-time: sent/pending/failed/retry
│   └── send_log.txt         # Detailed send history
├── campaign_20260506_154500/
└── ...

campaigns.db                # SQLite tracking database
```

---

## 📧 Campaign Brief Format

**brief.json:**
```json
{
  "campaign_id": "campaign_20260506_153000",
  "name": "Q2 ABM Outreach",
  "account_number": "1",
  "account_name": "Alina Khan (ABM)",
  "created_at": "2026-05-06T15:30:00",
  "status": "active",
  "total_recipients": 350,
  "email_sequences": [
    {
      "step": 1,
      "delay_days": 0,
      "subject": "First Email Subject",
      "body": "<p>HTML email body...</p>"
    },
    {
      "step": 2,
      "delay_days": 3,
      "subject": "Follow-up Subject",
      "body": "<p>Follow-up body...</p>"
    }
  ]
}
```

---

## 📊 Progress Tracking

**progress.json** (auto-updated):
```json
{
  "campaign_id": "campaign_20260506_153000",
  "total_recipients": 350,
  "sent": 142,
  "pending": 201,
  "failed": 7,
  "current_step": 1,
  "send_details": [
    {
      "recipient": "user@email.com",
      "step": 1,
      "status": "sent",
      "message_id": "AAMkADEyOTRhNGZlLTg5NWYt...",
      "sent_at": "2026-05-06T15:32:00",
      "retry_count": 0
    }
  ]
}
```

**Statuses:**
- `pending` - Ready to send (or queued for retry)
- `sent` - Email sent successfully
- `failed` - Max retries exceeded (2x)

---

## 🔄 How Threading Works

1. **Step 1 (Day 0):** Email sent, messageId captured
2. **Step 2 (Day 3):** Email sent with `inReplyTo: step1_messageId`
   - Appears as reply in recipient's inbox
   - Shows conversation thread
3. **Step 3 (Day 7):** Email sent with `inReplyTo: step2_messageId`
   - Continues conversation chain

---

## ⏱️ Rate Limiting

- **Delay:** 4-5 minutes (random) between each send
- **Reason:** Avoid bulk/spam detection
- **Scale:** 300 recipients = ~20-25 hours spread

Example: 300 recipients × 5min avg = 1500min ÷ 60 = 25 hours

---

## 🔁 Retry Logic

- **1st send:** If failed → retry
- **2nd attempt:** If failed → retry
- **3rd failure:** Mark as failed, skip

**Tracked in:** `send_details[].retry_count`

---

## 🔐 Satellite Accounts

| # | Account | Client ID |
|---|---------|-----------|
| 1 | Alina Khan (ABM) | 8039969b-8820-43e1-ac6d-437f33ec09b8 |
| 2 | Archita Singh (ABM) | 7b2be1f0-5ac7-4c1b-8219-8aa6082c923f |
| 3 | Sneha Malhotra (ABM) | df770948-6140-44df-baf6-e9c5ec7f8cee |
| 4 | Tanushree Kalita (ABM) | a1997674-4bcd-4e9a-ae05-18a18ccc1903 |

**Note:** All secrets and credentials stored in `.env` only (Client Credentials OAuth)

---

## 📝 Recipient CSV Format

**recipients.csv:**
```
email
user1@company.com
user2@company.com
user3@company.com
```

---

## 🖥️ Dashboard Features

- **Real-time updates** (refreshes every second)
- **Progress bars** (% sent per campaign)
- **Stats cards** (sent/pending/failed counts)
- **Status badges** (active/paused)
- **API endpoints** (for integration)

**API Routes:**
```
GET /                           # Dashboard HTML
GET /api/campaigns              # All campaigns JSON
GET /api/campaign/<id>          # Single campaign details
```

---

## 📋 Example Workflow

### Step 1: Create Campaign

```bash
$ python campaign_manager.py create

Campaign name? Q2 ABM Outreach
Account (1-4)? 1
Paste recipient list (one email per line):
alice@company.com
bob@company.com
charlie@company.com

Email Sequence Step 1:
  Subject? "Let's talk about your ABM strategy"
  Body? "<p>Hi there...</p>"
  Delay (days from step 1)? [0] 0

Email Sequence Step 2:
  Subject? "Following up on ABM..."
  Body? "<p>Just checking...</p>"
  Delay (days from step 1)? [0] 3

Add another sequence? (y/n) [n] n

[OK] Campaign created: campaign_20260506_153000
```

### Step 2: Run Scheduler

```bash
$ python scheduler.py campaign_20260506_153000

============================================================
SCHEDULER: Q2 ABM Outreach
============================================================
Account: Alina Khan (ABM)
Recipients: 3
Status: 0 sent | 3 pending | 0 failed

[STEP 1] Let's talk about your ABM strategy
  WAIT 287s before sending to alice@company.com...
  ✓ Sent to alice@company.com
  WAIT 293s before sending to bob@company.com...
  ✓ Sent to bob@company.com
  WAIT 256s before sending to charlie@company.com...
  ✓ Sent to charlie@company.com

[DONE] Campaign complete
  Sent: 3
  Failed: 0
```

### Step 3: Monitor Dashboard

```bash
$ python dashboard.py
Dashboard starting on http://localhost:5000
```

Open http://localhost:5000 → see campaign progress in real-time

---

## 🛠️ Commands Reference

| Command | Purpose |
|---------|---------|
| `python campaign_manager.py create` | Create new campaign |
| `python campaign_manager.py list` | List all campaigns |
| `python scheduler.py <campaign_id>` | Run campaign scheduler |
| `python dashboard.py` | Start web dashboard |
| `python send_email.py --help` | Direct email send (advanced) |

---

## 📂 File Locations

- **Scripts:** Root directory (`*.py`)
- **Campaign data:** `campaigns/campaign_*/`
- **Database:** `campaigns.db`
- **Logs:** `campaigns/campaign_*/send_log.txt`

---

## ⚙️ Requirements

```
requests            # Microsoft Graph API
flask               # Dashboard web server
python 3.8+
```

Install: `pip install requests flask`

---

## 🐛 Troubleshooting

**"Campaign not found"**
- Check: `python campaign_manager.py list`
- Verify campaign folder exists in `campaigns/`

**"Failed to get token"**
- Check credentials in `send_email.py`
- Verify Azure AD account permissions

**"Max retries exceeded"**
- Check recipient email validity
- Review Graph API response in `send_log.txt`
- Check account permissions in Azure

**Dashboard not loading**
- Ensure Flask installed: `pip install flask`
- Check port 5000 not in use

---

## 📞 Support

For Graph API issues → [Microsoft Graph Docs](https://learn.microsoft.com/graph)
For campaign issues → Check `campaigns/<id>/send_log.txt`

---

## 🎯 Next Steps

1. **Create first campaign** → `python campaign_manager.py create`
2. **Test with small group** → 5-10 recipients
3. **Monitor dashboard** → http://localhost:5000
4. **Review send logs** → `campaigns/<id>/send_log.txt`
5. **Scale to 300-400** → Once confident
