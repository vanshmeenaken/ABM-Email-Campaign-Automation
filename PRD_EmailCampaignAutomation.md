# Product Requirements Document
## Ken Research — Email Campaign Automation Agent
**Version:** 1.0  
**Owner:** Ken Research  
**Status:** Live / Production  

---

## 1. Product Overview

The Ken Research Email Campaign Automation Agent is a web-based outreach platform that enables the Ken Research team to create, send, track, and analyse multi-step email campaigns through 4 dedicated Microsoft 365 satellite accounts. It is designed for B2B outreach at scale — supporting up to 3-step drip sequences, per-recipient personalisation, email validation, open tracking, and automated reply detection.

The system is fully self-hosted (deployed on Render), uses Supabase PostgreSQL for state persistence, and communicates with Microsoft 365 via the Graph API. It requires no third-party CRM and can be integrated with external systems through its JSON API endpoints.

---

## 2. Problem Statement

The Ken Research outreach team was manually sending personalised emails one-by-one from shared satellite accounts with no visibility into opens, replies, or delivery failures. There was no way to run structured follow-up sequences, track performance, or recover from interruptions. This PRD documents the automated system built to replace that manual process.

---

## 3. Goals

| Goal | Metric |
|------|--------|
| Enable multi-step drip campaigns | Up to 3 sequential steps per campaign |
| Automate follow-up scheduling | Configurable delays in days + minutes |
| Avoid duplicate or missed sends | Zero duplicate sends on restart |
| Track email engagement | Open rate, reply rate per campaign and per day |
| Protect sender reputation | 4-5 min anti-spam gap, Bouncify pre-validation |
| Provide actionable dashboard | Real-time campaign stats with daily summary |

---

## 4. Scope

### In Scope
- Campaign creation UI (web form)
- Multi-step email sequencing with configurable delays
- Bulk send via 4 Microsoft 365 satellite accounts
- Per-recipient personalisation ({First Name}, {Company})
- Email validation via Bouncify API
- File attachment support (images inline, PDFs/Excel as attachments)
- Open tracking via 1×1 pixel
- Reply detection via inbox polling
- Campaign state persistence and restart recovery
- Dashboard: campaign list, daily summary, recent opens/replies
- Campaign detail page: per-recipient delivery and validation status
- Delete campaigns from dashboard
- JSON API for external integration

### Out of Scope
- CRM synchronisation (not built in, can be done via API)
- A/B testing of email variants
- Unsubscribe link management
- Bounce handling (handled implicitly by Bouncify skip)
- Scheduling campaigns for future start time

---

## 5. User Roles

| Role | Access | Description |
|------|--------|-------------|
| Campaign Manager | Full | Creates and monitors campaigns |
| Viewer | Read-only (dashboard) | Views stats but does not launch campaigns |
| System | Background | Auto-resume worker, reply checker (no UI) |

---

## 6. Sender Accounts

| # | Name | Microsoft 365 Account | App Registration |
|---|------|-----------------------|------------------|
| 1 | Alina Khan | alina.khan@kenresearch.com | Azure AD App: 8039969b |
| 2 | Archita Singh | archita.singh@kenresearch.com | Azure AD App: 7b2be1f0 |
| 3 | Sneha Malhotra | sneha.malhotra@kenresearch.com | Azure AD App: df770948 |
| 4 | Tanushree Kalita | tanushree.kalita@kenresearch.com | Azure AD App: a1997674 |

Each account is authenticated via Azure AD OAuth2 (client credentials flow) with `Mail.Send` and `Mail.Read` Application permissions granted.

---

## 7. Core Features

### 7.1 Campaign Creation

**Entry point:** `/send` (GET → form, POST → submit)

**Required inputs:**
- Sender Account (1 of 4 satellite accounts)
- Campaign Name (user-defined label shown on dashboard)
- Recipients (pasted text — see Section 8)
- Step 1 Subject and Body

**Optional inputs:**
- Campaign ID (auto-generated if left blank: `camp_YYYYMMDD_HHMM`)
- Step 2 (follow-up): enabled via checkbox, requires delay and content
- Step 3 (final nudge): enabled only if Step 2 enabled
- File attachments per step (images, PDF, Excel, Word, CSV)

**Personalisation markers** (replaced per recipient before send):

| Marker Variants | Replaced With |
|-----------------|---------------|
| `{First Name}`, `[First Name]`, `{Name}`, `[Name]` | Recipient's first name |
| `{Company}`, `[Company]`, `{Company Name}`, `[Company Name]` | Recipient's company |

**Step delays:** Each follow-up step has a delay defined in days + minutes from the previous step's completion. Minutes field exists for testing without waiting days.

**Body formatting:** Plain text is automatically converted to HTML (newlines → `<br>`, paragraph breaks → `<p>` tags). If the body already contains HTML tags, it is passed through unchanged.

---

### 7.2 Recipient Parsing

The recipients textarea accepts three input formats with automatic detection:

**Format A — Header-aware paste (from Excel / Google Sheets):**  
If the first line contains column headers (Email, Full Name, Company Name, LinkedIn, etc.), the parser reads column names to map indices precisely. Rows with empty or "NA" email are silently skipped.

Supported header variants:
- Email → `email`, `Email`
- Name → `full name`, `Full Name`, `Name`, `prospect_full`
- Company → `company name`, `Company Name`, `company`, `organisation`

**Format B — Headerless tab-separated:**  
Auto-detects email column (column containing `@`). Takes first non-URL, non-phone text column as name (first word only) and second as company.

**Format C — Comma-separated:**
```
First Name, Company, email@example.com
First Name, email@example.com
email@example.com
```

**Automatic filters applied in all modes:**
- LinkedIn URLs filtered out
- Phone numbers filtered out
- "NA", "N/A", "-", "--" values treated as empty
- Website domains filtered out
- Internal domain emails (kenresearch.com) bypass Bouncify validation

---

### 7.3 Email Sending

Emails are sent via **Microsoft Graph API** (`POST /users/{sender}/sendMail`).

**Authentication:** Per-account OAuth2 token fetched from Azure AD on each send.

**Email construction:**
1. Personalise subject and body per recipient
2. Convert plain text to HTML if needed
3. Apply attachment markers and build Graph attachment payload
4. Embed tracking pixel in body (1×1 transparent PNG)
5. POST to Graph API

**Anti-spam gap:** 4–5 minutes random delay between successive emails sent from the same account within one campaign step.

**Saved to Sent Items:** Yes (Graph API `saveToSentItems: true`).

---

### 7.4 Email Validation (Bouncify)

Before sending Step 1 emails, each recipient is validated via the Bouncify API.

| Result | Action |
|--------|--------|
| `deliverable` → "valid" | Email is sent |
| `undeliverable` → "invalid" | Email skipped, marked `status=skipped` |
| `risky` | Email skipped, marked `status=skipped` |
| `unknown` / API error | Email sent anyway |

**Cost optimisation:** Validation runs on Step 1 only. Once validated, subsequent steps skip validation.

**Bypass:** Emails from `INTERNAL_DOMAINS` (kenresearch.com) are never sent to Bouncify.

---

### 7.5 Multi-Step Drip Sequencing

A campaign can have 1, 2, or 3 steps. Steps run sequentially.

**Step flow:**
```
Launch →  Step 1 (immediate)  →  Wait N days/min  →  Step 2  →  Wait N days/min  →  Step 3  →  Completed
```

**Per-step state:** Campaign status is `active` (sending), `waiting` (between steps), or `completed`.

**Recipient filtering per step:**
- Skip recipients already sent on this step
- Skip recipients who replied (no further outreach)
- Skip recipients marked `failed` or `skipped` on Step 1

**Manual resume:** Dashboard "Action" button lets the team skip the wait and send a step immediately.

**Restart recovery:** On application restart, all non-completed campaigns are automatically resumed from where they left off using persisted state in the database.

**Duplicate guard:** An in-memory lock (`_running_campaigns` set + threading.Lock) prevents the same campaign from spawning two concurrent worker threads.

---

### 7.6 File Attachments

File attachments are uploaded per step in the campaign creation form and stored base64-encoded in the `attachments` table. They are loaded once per step and applied to every recipient.

**Supported file types:** Images (PNG, JPG, GIF, etc.), PDF, Excel, Word, CSV, PowerPoint.

**Placement markers in email body:**

| Marker | Behaviour |
|--------|-----------|
| `{image}` or `[image]` | Image embedded inline in email body using CID reference |
| `{file}` or `[file]` or `{attachment}` | File name reference inserted; file sent as attachment |

If no marker is present, images are appended at the bottom of the body and other files are attached silently.

Multiple files: markers are replaced in order (first marker → first file of that type).

---

### 7.7 Open Tracking

Each email contains an embedded 1×1 transparent PNG pixel served from `/track/pixel`.

**Pixel URL format:**
```
/track/pixel?campaign_id=<id>&recipient=<email>&step=<step>
```

**On pixel request:**
- If recipient domain is in `INTERNAL_DOMAINS` → skip logging (prevents internal team opens from polluting metrics)
- Else → insert row into `opens` table with campaign_id, recipient, step, timestamp, user_agent, IP

**Open rate calculation (per campaign):** `COUNT(DISTINCT recipient) / total_sent × 100`  
**Open rate calculation (daily summary):** For emails sent on day X, how many of those specific (campaign_id, recipient) pairs ever opened — avoids inflation from cross-day comparisons.

---

### 7.8 Reply Detection

A background daemon thread (`reply_checker_worker`) polls all sender inboxes every 60 seconds.

**Per-campaign check:**
1. Load campaign brief to get sender account number
2. Call Graph API: `GET /users/{sender}/mailFolders/Inbox/messages` filtered by `receivedDateTime >= campaign.created_at`
3. For each inbox message, match `from_email` against unreplied recipients
4. On match: set `replied=True`, `replied_at`, `reply_subject`, `reply_preview` (200 chars) in send_details

**Effect on sending:** Replied recipients are excluded from all subsequent steps.

---

## 8. Dashboard

**URL:** `/` (auto-refreshes every 20 seconds)

### 8.1 Summary Cards
- Total Campaigns
- Total Emails Sent
- Total Unique Opens
- Average Open Rate

### 8.2 Campaigns Table

Columns: Campaign Name/ID | Account | Sent/Total | Undelivered | Opens | Replied | Open Rate | Last Open | Action | Delete

**Undelivered column:** Shows count of failed + Bouncify-skipped emails as a red badge. Hover tooltip shows breakdown (X failed · Y skipped).

**Action column:**
- `✓ Completed` — all steps done
- `⏱ Step X due in Yh Zm` (amber button) — click to skip wait and send now
- `▶ Resume Step X (Y left)` (orange button) — pending sends in active step
- `—` — no action needed

**Delete column:** Trash icon with browser confirm dialog. Deletes campaign, opens, and attachments records permanently.

**Validation summary** (under campaign name): "✓ N valid · ✗ N skipped" shown if Bouncify checked the campaign.

**Multi-step status** (under campaign name): "Sending Step 1/3", "Step 2/3 — in 14h 52m", "All 3 steps done".

### 8.3 Daily Summary Table (last 30 days)
Columns: Date | Campaigns | Emails Sent | Unique Opens | Open Rate | Replies | Reply Rate

### 8.4 Recent Opens Panel
Last 10 tracked opens with recipient email, campaign ID, and timestamp.

### 8.5 Recent Replies Panel
Last 10 replies with recipient name, reply subject, body preview, and timestamp.

---

## 9. Campaign Detail Page

**URL:** `/campaign/<campaign_id>`

### Row 1 — Delivery Status Cards
| Card | Value |
|------|-------|
| Total | All recipients |
| Delivered | `status = sent` |
| Undelivered | `status = failed or skipped` (breakdown: X failed · Y skipped) |
| Pending | Not yet processed |

### Row 2 — Validation Status Cards
| Card | Value |
|------|-------|
| Valid | Bouncify returned "deliverable" |
| Invalid | Bouncify returned "undeliverable" |
| Risky | Bouncify returned "risky" |
| Unknown | No check result |

### Recipient Breakdown Table

| Column | Values |
|--------|--------|
| Email | Mono font |
| Name | First name or — |
| Company | Company or — |
| Validation | ✓ Valid / ✗ Invalid / ⚠ Risky / ? Unknown / Not checked |
| Status | ✓ Delivered (green row) / ✗ Undelivered + reason (red row) / Pending |
| Steps Done | "1, 2" — which steps completed |
| Replied | ✓ Yes or — |

---

## 10. API Reference (JSON Endpoints)

### `GET /api/metrics/<campaign_id>`
Returns campaign summary for external integration.

**Response:**
```json
{
  "campaign_id": "camp_20260619_1000",
  "status": "completed",
  "total_sent": 98,
  "pending": 0,
  "opens": 58,
  "open_rate": "59.2%",
  "last_open": "2026-06-18T10:30:00"
}
```

### `GET /api/opens?campaign_id=<id>&since=<ISO_datetime>`
Returns raw opens data for a campaign, optionally filtered by timestamp.

**Response:**
```json
{
  "opens": [
    {
      "campaign_id": "camp_20260619_1000",
      "recipient": "email@example.com",
      "step": 1,
      "timestamp": "2026-06-19T08:22:11",
      "user_agent": "...",
      "ip_address": "..."
    }
  ],
  "count": 1
}
```

### `GET /health`
Returns `{"status": "ok"}` — for uptime monitoring and load balancer health checks.

---

## 11. Data Model

### `campaigns` table

| Field | Type | Description |
|-------|------|-------------|
| campaign_id | TEXT PK | Unique identifier (e.g., `camp_20260619_1000`) |
| brief | JSONB | Campaign metadata (name, account, sequences, created_at) |
| progress | JSONB | Real-time state (sent, pending, campaign_status, send_details) |
| created_at | TIMESTAMPTZ | Auto-generated |

**Key JSONB fields in `brief`:**
```json
{
  "campaign_id": "camp_20260619_1000",
  "name": "India MedTech — June 2026",
  "account_number": "1",
  "account_name": "Alina Khan",
  "created_at": "2026-06-19T10:00:00",
  "total_recipients": 100,
  "total_steps": 3,
  "email_sequences": [
    {"step": 1, "subject": "...", "body": "...", "delay_days": 0, "delay_minutes": 0},
    {"step": 2, "subject": "...", "body": "...", "delay_days": 3, "delay_minutes": 0},
    {"step": 3, "subject": "...", "body": "...", "delay_days": 2, "delay_minutes": 0}
  ]
}
```

**Key JSONB fields in `progress`:**
```json
{
  "campaign_status": "waiting",
  "current_step": 2,
  "next_step_send_at": "2026-06-22T10:00:00",
  "sent": 98,
  "pending": 2,
  "failed": 0,
  "send_details": [
    {
      "recipient": "email@example.com",
      "first_name": "Amit",
      "company": "Acme Corp",
      "status": "sent",
      "steps_completed": [1],
      "sent_at": "2026-06-19T10:05:00",
      "validation_status": "valid",
      "validation_result": "deliverable",
      "replied": false,
      "replied_at": null,
      "reply_subject": null,
      "reply_preview": null
    }
  ]
}
```

### `opens` table

| Field | Type | Description |
|-------|------|-------------|
| id | SERIAL PK | |
| campaign_id | TEXT | Which campaign |
| recipient | TEXT | Email that opened |
| step | INTEGER | Which step was opened |
| timestamp | TEXT | ISO datetime of open |
| user_agent | TEXT | Client info |
| ip_address | TEXT | Opener's IP |

### `attachments` table

| Field | Type | Description |
|-------|------|-------------|
| id | SERIAL PK | |
| campaign_id | TEXT | Which campaign |
| step | INTEGER | Which step (1-3) |
| filename | TEXT | Original filename |
| content_type | TEXT | MIME type |
| content_b64 | TEXT | Base64-encoded file |
| created_at | TIMESTAMPTZ | Auto-generated |

---

## 12. Technical Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Browser (User)                         │
│         dashboard.html / send.html / campaign_detail.html │
└─────────────────────────┬────────────────────────────────┘
                          │ HTTP
┌─────────────────────────▼────────────────────────────────┐
│                   Flask App (Render)                      │
│                                                           │
│  Routes:  /  /send  /campaign/<id>  /delete/<id>          │
│           /resume/<id>  /track/pixel  /api/*  /health     │
│                                                           │
│  Background Threads:                                      │
│   • bulk_send_worker (one per active campaign)            │
│   • reply_checker_worker (polls every 60s)                │
│   • auto_resume_pending_campaigns (runs on startup)       │
└──────┬─────────────────┬───────────────────┬─────────────┘
       │                 │                   │
┌──────▼──────┐  ┌───────▼──────┐  ┌────────▼────────┐
│  Supabase   │  │ Microsoft    │  │  Bouncify API   │
│ PostgreSQL  │  │ Graph API    │  │ (email validate) │
│             │  │              │  └─────────────────┘
│ campaigns   │  │ sendMail     │
│ opens       │  │ Inbox read   │
│ attachments │  │ OAuth token  │
└─────────────┘  └──────────────┘
```

**Hosting:** Render (web service, auto-deploy from GitHub main branch)  
**Database:** Supabase PostgreSQL with SSL  
**Language:** Python 3, Flask  
**Frontend:** Jinja2 + Tailwind CSS (CDN)  
**Auth:** Azure AD OAuth2, client credentials flow  
**Email:** Microsoft Graph API v1.0  

---

## 13. Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | Supabase PostgreSQL connection string |
| `FLASK_SECRET_KEY` | ✅ | Flask session secret |
| `TENANT_ID` | ✅ | Azure AD tenant ID |
| `ACCOUNT_1_CLIENT_ID` | ✅ | Alina Khan app client ID |
| `ACCOUNT_1_CLIENT_SECRET` | ✅ | Alina Khan app secret |
| `ACCOUNT_1_EMAIL` | ✅ | alina.khan@kenresearch.com |
| `ACCOUNT_2_CLIENT_ID` | ✅ | Archita Singh app client ID |
| `ACCOUNT_2_CLIENT_SECRET` | ✅ | Archita Singh app secret |
| `ACCOUNT_2_EMAIL` | ✅ | archita.singh@kenresearch.com |
| `ACCOUNT_3_CLIENT_ID` | ✅ | Sneha Malhotra app client ID |
| `ACCOUNT_3_CLIENT_SECRET` | ✅ | Sneha Malhotra app secret |
| `ACCOUNT_3_EMAIL` | ✅ | sneha.malhotra@kenresearch.com |
| `ACCOUNT_4_CLIENT_ID` | ✅ | Tanushree Kalita app client ID |
| `ACCOUNT_4_CLIENT_SECRET` | ✅ | Tanushree Kalita app secret |
| `ACCOUNT_4_EMAIL` | ✅ | tanushree.kalita@kenresearch.com |
| `BOUNCIFY_API_KEY` | ⚠️ Optional | Email validation (skipped if missing) |
| `TRACKER_URL` | ⚠️ Optional | Base URL for tracking pixel (auto-detected on Render) |
| `PORT` | ⚠️ Optional | Flask port (default 5000) |

---

## 14. Integration Guide

The system exposes JSON endpoints that allow external tools (CRMs, dashboards, automation workflows) to read campaign data.

### Read campaign metrics
```
GET /api/metrics/<campaign_id>
```

### Read open events
```
GET /api/opens?campaign_id=<id>
GET /api/opens?since=2026-06-01T00:00:00
```

### Health check (for uptime monitors)
```
GET /health
→ {"status": "ok"}
```

### Triggering campaigns programmatically
Currently, campaigns are created through the web form only. For programmatic launch, the `/send` POST endpoint accepts standard form data:

| Field | Type | Required |
|-------|------|----------|
| `account` | "1"–"4" | ✅ |
| `campaign_name` | string | ✅ |
| `recipients` | multiline string | ✅ |
| `subject_1` | string | ✅ |
| `body_1` | string | ✅ |
| `campaign_id` | string | No (auto-generated) |
| `subject_2` | string | No |
| `body_2` | string | No |
| `delay_days_2` | integer | No (default 2) |
| `delay_minutes_2` | integer | No (default 0) |
| `subject_3` | string | No |
| `body_3` | string | No |
| `delay_days_3` | integer | No (default 2) |
| `delay_minutes_3` | integer | No (default 0) |
| `tracker_url` | string | No (auto-detected) |
| `attachments_1` | file(s) | No |
| `attachments_2` | file(s) | No |
| `attachments_3` | file(s) | No |

---

## 15. Known Constraints & Limitations

| Constraint | Detail |
|------------|--------|
| Max campaign steps | 3 |
| Sender accounts | 4 (fixed; adding a 5th requires code + Azure app setup) |
| Send rate | 1 email per 4-5 min per campaign (anti-spam) |
| Attachment storage | Base64 in DB — large files increase DB size significantly |
| Reply detection | Polling-based (60s lag); not real-time |
| Open tracking | Pixel-based; blocked by email clients that disable images |
| State recovery | In-memory lock lost on restart — resume worker re-checks DB on boot |
| Bouncify credits | Consumed per unique email on Step 1 only |
| Concurrent campaigns | No limit on simultaneous campaigns; each gets its own thread |

---

## 16. Security Notes

- Client secrets are stored only in Render environment variables — never in code or git
- No user authentication on the dashboard (internal tool — network/access controlled)
- SQL parameters are always passed as parameterised queries (no string interpolation)
- File uploads are stored as base64 strings — no filesystem writes
- Tracking pixel does not expose PII beyond what is already in the email

---

*Document generated: June 2026*  
*System repository: ABM-Email-Campaign-Automation (private)*  
*Deployed at: https://abm-email-campaign-automation-1.onrender.com*
