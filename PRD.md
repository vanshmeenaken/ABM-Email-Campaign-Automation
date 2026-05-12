# Product Requirements Document (PRD)
## Ken Research — Email Campaign Automation System

**Version:** 1.0
**Last Updated:** 12 May 2026
**Document Owner:** Ken Research Ops Team
**Status:** Live (Local Deployment)

---

## 1. Executive Summary

The **Ken Research Email Campaign Automation System** is a self-hosted Flask web application that enables the Ken Research team to send tracked B2B outreach emails through 4 Azure AD satellite accounts (Alina Khan, Archita Singh, Sneha Malhotra, Tanushree Kalita). The system embeds a 1x1 transparent pixel into every email to track opens, records them to a local database, and presents real-time campaign analytics through a clean web dashboard.

The product was built to replace a CLI-based workflow with a non-technical web interface, making it accessible to the entire Ken Research operations team without requiring command-line knowledge.

---

## 2. Problem Statement

### Before this system existed:
- Team had a working CLI (`send_email.py`) but only technical users could operate it.
- Bulk sending required manually editing JSON campaign briefs and running `scheduler.py` in a terminal.
- No visibility into email open rates — no tracking pixel infrastructure.
- Querying campaign stats required running `metrics.py` and parsing terminal output.
- Pixel tracking, when added, only worked on the sender's machine (localhost), not for the team.
- Restarting the app caused in-progress bulk campaigns to silently die mid-send.

### What this system solves:
1. Non-technical team members can send emails through a web UI.
2. Multiple recipients can be entered in one go (bulk send).
3. Every email is tracked automatically — no flags or configuration needed.
4. Open rates are visible in real-time on a dashboard.
5. Campaigns auto-resume if the app crashes or restarts.
6. Team members on the same network can trigger pixel events (their opens get tracked centrally).

---

## 3. Target Users & Personas

### Primary Users:
| Persona | Role | Technical Skill | Usage Pattern |
|---------|------|-----------------|---------------|
| **Operations Lead** | Vansh (admin) | Medium-High | Runs the app on their laptop, sends bulk campaigns, monitors stats |
| **ABM Team Members** | Sales/ops team | Low-Medium | Open the dashboard URL, send their own campaigns, check open rates |

### Secondary Users:
- **Future Engineering Maintainers** — Need to understand architecture to extend or migrate.
- **Recipients** — External prospects who open emails (passive trigger of pixel tracking).

---

## 4. Goals & Success Metrics

### Product Goals:
1. **Zero CLI dependency** — Team can do 100% of tasks via browser.
2. **Real-time visibility** — Open events visible on dashboard within 20 seconds.
3. **Reliability** — Bulk campaigns complete successfully even after app restart.
4. **Zero recurring cost** — Run on free infrastructure.

### Success Metrics:
- ≥90% of bulk campaigns complete without manual intervention.
- ≥95% of email opens recorded by tracker (when team is on same network).
- Dashboard updates within 20 seconds of any state change.
- Free tier deployment cost: **$0/month**.

---

## 5. Scope

### IN SCOPE:
- Sending single or bulk emails via 4 pre-configured Azure AD accounts.
- Embedding tracking pixel in every email automatically.
- Recording open events to a local SQLite database.
- Web dashboard with campaign list, sent counts, open rates, recent opens.
- Auto-refresh of dashboard every 20 seconds.
- Background bulk send with random 4-5 minute delays.
- Auto-resume of pending campaigns on app startup.
- Manual "Resume" button for stalled campaigns.
- Network-IP-based tracker URL (works for team on same WiFi).
- GitHub-based source control with secrets excluded.

### OUT OF SCOPE (current version):
- Click-through tracking (no CTR for PDF/Excel attachments — files don't ping back).
- Email validation (Bouncify integration exists in CLI but not wired into dashboard).
- Multi-step email sequences (drip campaigns) — present in `scheduler.py` but not dashboard.
- Attachment upload via UI (must be embedded in HTML body for now).
- User authentication (anyone with network access can use the dashboard).
- Email reply tracking.
- A/B testing.
- Production cloud deployment (Render config exists, not yet deployed).
- Persistent database for production (SQLite is ephemeral on Render free tier).

---

## 6. User Flows

### 6.1 Send a Single Email
1. User opens `http://172.16.16.1:5000/send`.
2. Selects a Sender Account (1 of 4) from dropdown.
3. Enters one recipient email.
4. Optionally edits Campaign ID (pre-populated with `camp_YYYYMMDD_HHMM`).
5. Enters Subject (or uses default).
6. Enters Message body (HTML supported).
7. Clicks **Send Email**.
8. App creates a campaign folder, sends the email with pixel embedded, updates `progress.json`.
9. User redirected back with success flash message.
10. Campaign appears immediately in dashboard.

### 6.2 Send a Bulk Email
1. Same as above, but user enters multiple recipient emails (one per line) in the textarea.
2. On submit, app creates the campaign folder with all recipients marked "pending".
3. A background daemon thread (`bulk_send_worker`) starts processing recipients.
4. For each recipient: random sleep 240–300 seconds → send → update `progress.json`.
5. Dashboard auto-refreshes every 20 seconds, showing live progress.

### 6.3 View Campaign Stats
1. User opens `http://172.16.16.1:5000/` (dashboard).
2. Sees 4 summary cards: Total Campaigns, Emails Sent, Total Opens, Avg Open Rate.
3. Sees campaigns table with: Campaign Name/ID, Account, Sent/Total, Opens, Open Rate, Last Open, Action.
4. Sees Recent Opens panel (last 10 tracked opens).
5. Page auto-refreshes every 20 seconds.

### 6.4 Resume a Stalled Campaign
1. User notices a campaign with "▶ Resume (N pending)" in the Action column.
2. Clicks Resume.
3. App reads `progress.json`, finds pending recipients, spawns new `bulk_send_worker` for them.
4. Flash message confirms resume.
5. Pending emails send with 4-5 min gaps.

### 6.5 Open Event Tracking
1. Recipient receives the email.
2. Email client renders HTML, including the embedded `<img>` tag pointing to the tracker URL.
3. Image is fetched: `GET http://172.16.16.1:5000/track/pixel?campaign_id=X&recipient=Y&step=1`.
4. App writes a row to `opens` table in `email_opens.db`.
5. App returns a 1x1 transparent PNG.
6. Dashboard (on next 20-second refresh) shows the new open.

### 6.6 Auto-Resume on App Startup
1. App starts (e.g., user runs `python app.py`).
2. `auto_resume_pending_campaigns()` scans `campaigns/` folder.
3. For each campaign with pending recipients in `send_details`, spawns a `bulk_send_worker` thread.
4. Logs `[AUTO-RESUME] <campaign_id>: N pending recipients` to console.
5. Pending sends continue automatically.

---

## 7. Functional Requirements

### 7.1 Email Sending
- **FR-1**: System MUST send emails using Microsoft Graph API `/sendMail` endpoint.
- **FR-2**: System MUST authenticate using Azure AD OAuth 2.0 client credentials flow.
- **FR-3**: System MUST support 4 distinct satellite accounts (Alina, Archita, Sneha, Tanushree).
- **FR-4**: System MUST embed a 1x1 transparent PNG tracking pixel in every email body when a campaign ID is provided.
- **FR-5**: Email body MUST support HTML formatting.
- **FR-6**: System MUST save sent emails to the sender's Sent Items folder (`saveToSentItems: true`).

### 7.2 Bulk Send
- **FR-7**: System MUST accept multiple recipients via newline-separated input.
- **FR-8**: System MUST process bulk sends in a background daemon thread (non-blocking).
- **FR-9**: System MUST wait a random interval between 240–300 seconds between each email in a bulk send.
- **FR-10**: System MUST persist progress after each successful send (recipient-level status in `progress.json`).
- **FR-11**: System MUST log every send attempt (success or failure) to `send_log.txt` inside the campaign folder.

### 7.3 Open Tracking
- **FR-12**: System MUST expose `GET /track/pixel` endpoint that accepts `campaign_id`, `recipient`, `step` query parameters.
- **FR-13**: Endpoint MUST insert a row into `opens` table with timestamp (UTC ISO), user agent, IP address.
- **FR-14**: Endpoint MUST return a 1x1 transparent PNG with `Content-Type: image/png`.
- **FR-15**: Tracker URL in emails MUST be auto-detected as: `RENDER_EXTERNAL_URL` env var > `TRACKER_URL` env var > local network IP > `localhost`.

### 7.4 Campaign Management
- **FR-16**: Every send (single or bulk) MUST create a campaign folder under `campaigns/<campaign_id>/`.
- **FR-17**: Each campaign folder MUST contain: `brief.json`, `progress.json`, `recipients.csv`, `send_log.txt`.
- **FR-18**: `progress.json` MUST initialize `send_details` array with all recipients (status: "pending") at creation time.
- **FR-19**: System MUST auto-resume any campaign with pending recipients on app startup.
- **FR-20**: System MUST provide a manual `/resume/<campaign_id>` POST endpoint.

### 7.5 Dashboard
- **FR-21**: Dashboard MUST display: Total Campaigns, Emails Sent, Total Opens, Avg Open Rate.
- **FR-22**: Dashboard MUST list every campaign with name, ID, account, sent/total, opens, open rate, last open timestamp.
- **FR-23**: Dashboard MUST show "Resume (N pending)" button for campaigns with pending recipients, "Done" otherwise.
- **FR-24**: Dashboard MUST display last 10 opens in a "Recent Opens" panel.
- **FR-25**: Dashboard MUST auto-refresh every 20 seconds via client-side JavaScript.
- **FR-26**: Avg Open Rate MUST exclude opens from deleted/non-existent campaigns.

### 7.6 API Endpoints (programmatic access)
- **FR-27**: `GET /api/opens?campaign_id=X&since=ISO_TIMESTAMP` MUST return JSON of opens.
- **FR-28**: `GET /api/metrics/<campaign_id>` MUST return campaign metrics JSON.
- **FR-29**: `GET /health` MUST return `{"status": "ok"}` with HTTP 200.

---

## 8. Non-Functional Requirements

### 8.1 Performance
- Single email send: complete within 3 seconds (excluding network latency to Microsoft Graph).
- Pixel endpoint: respond within 50 ms.
- Dashboard render: under 500 ms with up to 100 campaigns.

### 8.2 Reliability
- Bulk campaigns MUST survive app restarts via auto-resume.
- Progress MUST be persisted to disk after each successful send (no in-memory-only state).
- Database writes MUST use immediate commits (no batching).

### 8.3 Security
- Azure AD client secrets MUST NOT be hardcoded in source.
- Secrets MUST be loaded from `.env` via `python-dotenv`.
- `.env` MUST be excluded from git via `.gitignore`.
- `.env.example` MUST be committed as a template.
- GitHub push protection enforced — secrets in commits are rejected.

### 8.4 Usability
- No CLI knowledge required for daily use.
- Form labels in plain language ("To (Recipient Emails)", not "recipient_email").
- Helper text under each field.
- Error messages MUST be actionable (e.g., "Check your credentials" not "Status: 401").

### 8.5 Portability
- Must run on Windows 10+, macOS, Linux.
- Single command to start: `python app.py`.
- Deployable to Render/Heroku via `Procfile` and `render.yaml`.

---

## 9. Technical Architecture

### 9.1 Tech Stack
| Layer | Technology |
|-------|------------|
| Backend | Flask 2.3.3 + Python 3.11 |
| WSGI Server (prod) | Gunicorn 21.2.0 (1 worker, 4 threads) |
| Dev Server | Werkzeug (built into Flask) |
| Frontend | HTML5 + Tailwind CSS (via CDN, no build step) |
| Templating | Jinja2 (Flask default) |
| Database | SQLite (`email_opens.db`) |
| Campaign Storage | JSON files on disk (`campaigns/<id>/*.json`) |
| Email API | Microsoft Graph API |
| Authentication | Azure AD OAuth 2.0 (client credentials) |
| Env Management | `python-dotenv` 1.0.0 |
| HTTP Client | `requests` 2.31.0 |

### 9.2 File Structure
```
ken-email-sender/
├── app.py                      # Main Flask web app (unified)
├── send_email.py               # Email sending module (Graph API)
├── campaign_manager.py         # Legacy CLI campaign manager
├── scheduler.py                # Legacy CLI scheduler (ABM 4-5 min)
├── metrics.py                  # Legacy CLI metrics tool
├── email_tracker.py            # Legacy standalone pixel tracker
├── email_validator.py          # Bouncify validation (CLI only)
├── config.py                   # Environment config helpers
├── dashboard.py                # Legacy dashboard module
├── requirements.txt            # Python dependencies
├── .env                        # Secrets (NOT in git)
├── .env.example                # Secrets template (in git)
├── .gitignore                  # Excludes secrets, dbs, campaigns
├── render.yaml                 # Render deploy config
├── Procfile                    # Heroku/Render start command
├── START.bat                   # Windows quick-launch script
├── templates/
│   ├── base.html               # Layout (Tailwind, sidebar)
│   ├── dashboard.html          # Campaign stats page
│   └── send.html               # Send email form
├── campaigns/                  # Per-campaign data (NOT in git)
│   └── <campaign_id>/
│       ├── brief.json          # Campaign config (sequences, account, etc.)
│       ├── progress.json       # Send status per recipient
│       ├── recipients.csv      # Email list
│       └── send_log.txt        # Append-only send log
├── email_opens.db              # SQLite (NOT in git)
└── PRD.md                      # This document
```

### 9.3 Component Responsibilities

#### `app.py` (Primary Service)
- Flask web server.
- Routes: dashboard, send form, send submit, resume, pixel endpoint, API endpoints, health.
- Spawns background `bulk_send_worker` threads.
- Runs `auto_resume_pending_campaigns()` on startup.
- Initializes SQLite database on startup.

#### `send_email.py` (Email Sending Module)
- Acquires OAuth token from Azure AD using client credentials.
- Builds Microsoft Graph API request body.
- Embeds tracking pixel `<img>` tag if `campaign_id` provided.
- Returns `True` on success, `None` on failure.
- Reads credentials from environment variables (via `python-dotenv`).

#### `templates/` (UI)
- `base.html` — Sidebar nav, Tailwind CDN, flash messages, layout.
- `dashboard.html` — Stats cards, campaign table, recent opens, JS auto-refresh.
- `send.html` — Form with account dropdown, recipients textarea, campaign ID, subject, body.

### 9.4 Data Model

#### SQLite — `email_opens.db`
```sql
CREATE TABLE opens (
    id INTEGER PRIMARY KEY,
    campaign_id TEXT,
    recipient TEXT,
    step INTEGER,
    timestamp TEXT,         -- ISO 8601 UTC
    user_agent TEXT,
    ip_address TEXT
);
```

#### File — `brief.json` (per campaign)
```json
{
  "campaign_id": "camp_20260512_1303",
  "name": "Q2 Outreach",
  "account_number": "1",
  "account_name": "Alina Khan",
  "created_at": "2026-05-12T13:03:00",
  "status": "active",
  "total_recipients": 5,
  "email_sequences": [
    {
      "step": 1,
      "delay_days": 0,
      "delay_minutes": 0,
      "subject": "Quick intro...",
      "body": "<p>Hi there...</p>"
    }
  ]
}
```

#### File — `progress.json` (per campaign)
```json
{
  "campaign_id": "camp_20260512_1303",
  "total_recipients": 5,
  "sent": 2,
  "pending": 3,
  "failed": 0,
  "retry_queue": 0,
  "last_update": "2026-05-12T13:15:32",
  "current_step": 1,
  "send_details": [
    {
      "recipient": "lead1@company.com",
      "step": 1,
      "status": "sent",
      "message_id": null,
      "sent_at": "2026-05-12T13:05:11",
      "retry_count": 0
    },
    {
      "recipient": "lead2@company.com",
      "step": 0,
      "status": "pending",
      "message_id": null,
      "sent_at": null,
      "retry_count": 0
    }
  ]
}
```

### 9.5 API Endpoints

| Method | Path | Purpose | Auth | Request | Response |
|--------|------|---------|------|---------|----------|
| GET | `/` | Dashboard page | None | — | HTML |
| GET | `/send` | Send email form | None | — | HTML |
| POST | `/send` | Submit send request | None | Form: account, recipients, subject, body, campaign_id | Redirect to /send + flash |
| POST | `/resume/<id>` | Resume stalled campaign | None | — | Redirect to / + flash |
| GET | `/track/pixel` | Record open event | None | Query: campaign_id, recipient, step | 1x1 PNG |
| GET | `/api/opens` | Query opens (JSON) | None | Query: campaign_id, since | `{"opens": [...], "count": N}` |
| GET | `/api/metrics/<id>` | Campaign metrics | None | — | JSON metrics |
| GET | `/health` | Health check | None | — | `{"status": "ok"}` |

### 9.6 Environment Variables

#### Required (secrets, in `.env`):
```
TENANT_ID=<Azure AD Tenant ID>
ACCOUNT_1_CLIENT_ID=<Alina Khan client_id>
ACCOUNT_1_CLIENT_SECRET=<Alina Khan secret>
ACCOUNT_1_EMAIL=alina.khan@kenresearch.com
ACCOUNT_2_CLIENT_ID=<Archita Singh client_id>
ACCOUNT_2_CLIENT_SECRET=<Archita Singh secret>
ACCOUNT_2_EMAIL=archita.singh@kenresearch.com
ACCOUNT_3_CLIENT_ID=<Sneha Malhotra client_id>
ACCOUNT_3_CLIENT_SECRET=<Sneha Malhotra secret>
ACCOUNT_3_EMAIL=sneha.malhotra@kenresearch.com
ACCOUNT_4_CLIENT_ID=<Tanushree Kalita client_id>
ACCOUNT_4_CLIENT_SECRET=<Tanushree Kalita secret>
ACCOUNT_4_EMAIL=tanushree.kalita@kenresearch.com
```

#### Optional:
```
TRACKER_URL=http://172.16.16.1:5000   # Override auto-detected tracker URL
FLASK_SECRET_KEY=<random string>      # For Flask sessions (flash messages)
PORT=5000                             # Server port
FLASK_DEBUG=False                     # Debug mode
RENDER_EXTERNAL_URL=<auto-set>        # Set automatically by Render
```

---

## 10. UI Specification

### 10.1 Layout
- **Sidebar (dark, fixed left):** Logo "KEN RESEARCH / Email Campaigns", nav links (Campaign Stats, Send Email), status indicator ("4 satellite accounts ready" with green dots).
- **Main content (light gray bg):** Page title + content cards.

### 10.2 Dashboard Page (`/`)
- **Top row:** 4 summary cards (Total Campaigns, Emails Sent, Total Opens, Avg Open Rate).
- **Main area:** Two-column on large screens:
  - Left: "All Campaigns" table with countdown "Auto-refreshes in 20s".
  - Right: "Recent Opens" panel (last 10).
- **Campaign table columns:** Campaign (name + ID), Account, Sent (X/Y), Opens, Open Rate (color-coded badge), Last Open, Action (Resume button or "Done").

### 10.3 Send Email Page (`/send`)
- **Sender Account** — dropdown (required).
- **To (Recipient Emails)** — textarea, 4 rows, monospace (required).
- **Campaign ID** — text input pre-populated with `camp_YYYYMMDD_HHMM` (optional).
- **Subject** — text input (defaults to "Test Email - Ken Research Automation").
- **Message** — textarea, 6 rows (HTML supported).
- **Submit button** — large blue "Send Email" with icon.
- **Sender Accounts reference card** — shows all 4 accounts with green "Ready" status.

### 10.4 Visual Design
- **Colors:** Slate dark sidebar (`#1e3a5f`), white cards, blue primary (`bg-blue-600`).
- **Typography:** Tailwind defaults (sans-serif), monospace for IDs/emails.
- **Open Rate badges:** Green if >30%, yellow if ≤30%, gray if no data.
- **Flash messages:** Green for success, red for error, top of page.

---

## 11. Deployment

### 11.1 Local Development (Current Setup)
```bash
# One-time setup
git clone https://github.com/vanshmeenaken/ABM-Email-Campaign-Automation
cd ABM-Email-Campaign-Automation
pip install -r requirements.txt
cp .env.example .env
# (fill in real secrets in .env)

# Run
python app.py
# or double-click START.bat (Windows)
```
- Accessible at `http://localhost:5000` (you) or `http://<your-IP>:5000` (team on same WiFi).

### 11.2 Production Deployment (Render — Prepared, Not Yet Deployed)
1. Push repo to GitHub.
2. On Render: New Web Service → connect repo.
3. Auto-detected from `render.yaml`:
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn app:app --workers 1 --threads 4 --timeout 120`
   - Plan: Free
4. Add environment variables (all from `.env`) via Render dashboard.
5. Deploy. Render assigns URL like `https://ken-email-campaign.onrender.com`.
6. `RENDER_EXTERNAL_URL` is auto-set → tracker URLs in emails use the public URL.

### 11.3 Free Tier Considerations
- Render free tier spins down after 15 min of inactivity.
- First request after sleep takes ~30 sec to wake up.
- SQLite is ephemeral on Render free — opens data lost on redeploy.
- For persistent storage, upgrade to PostgreSQL addon (~$9/mo) — out of scope for v1.

### 11.4 Network Tracking (Current Constraint)
For pixel tracking to work for team members:
- Team must be on the **same WiFi/LAN** as the host machine.
- Windows Firewall must allow inbound TCP on port 5000.
- Office WiFi must NOT have "AP isolation" / "client isolation" enabled (some corporate networks do).

If office WiFi blocks device-to-device traffic, only a public deployment (Render/ngrok) will work for team tracking.

---

## 12. Configuration Reference

### 12.1 Bulk Send Delay
- Location: `app.py` → `bulk_send_worker()`
- Default: random uniform 240–300 seconds (4–5 min).
- To change: modify `random.uniform(240, 300)` literal.

### 12.2 Dashboard Auto-Refresh
- Location: `templates/dashboard.html` → `<script>` block.
- Default: 20 seconds.
- To change: modify `countdown = 20` literal.

### 12.3 Pixel PNG Bytes
- Location: `app.py` → `PIXEL` constant.
- Standard 1x1 transparent PNG (~67 bytes).

### 12.4 Account Display Names
- Location: `app.py` → `ACCOUNTS` dict.
- Maps account_num ("1"–"4") to display name.

---

## 13. Known Limitations

### Technical:
1. **Single Flask process** — Cannot horizontally scale. Threads are bound to one process.
2. **Daemon threads** — Killed on app shutdown. Mitigated by auto-resume, but in-flight emails can be lost if the app crashes mid-API-call.
3. **SQLite single-writer** — Concurrent pixel hits could (rarely) cause write contention. Not yet observed in practice.
4. **No retry logic** — A failed `send_email()` marks the recipient as failed; no automatic retry. (CLI scheduler has retries; the dashboard worker does not.)
5. **No email validation in dashboard flow** — `email_validator.py` exists but is not invoked from `bulk_send_worker`.

### Business:
1. **No multi-step sequences from dashboard** — Each campaign is a single email blast. Drip campaigns require editing `brief.json` manually and running CLI `scheduler.py`.
2. **No CTR tracking** — System sends PDFs/Excels as attachments, which cannot be tracked once delivered.
3. **No authentication** — Anyone with network access can use the dashboard.
4. **No audit log** — No record of WHO sent WHAT from the dashboard (no user accounts).

### Network:
1. **Local-only tracking** — Pixel URL embeds the local network IP. Team members on a different network (remote, mobile data, VPN) won't trigger tracking.
2. **App must be running** — If the host laptop is closed/asleep, no tracking and no sending.

---

## 14. Roadmap (Future Enhancements)

### Short Term (1–2 weeks):
- Deploy to Render free tier → public URL for tracking regardless of network.
- Add a simple basic-auth password to the dashboard.
- Add Bouncify email validation to the bulk send flow.

### Medium Term (1–2 months):
- Multi-step sequences from the dashboard (drip campaigns with day-based delays).
- Slack/email notification when a campaign completes.
- Export campaign stats to CSV.
- Per-recipient activity timeline.

### Long Term:
- Migrate to PostgreSQL for persistent multi-instance deployment.
- Add user accounts + role-based access.
- A/B testing for subject lines.
- Reply detection via Microsoft Graph webhooks.
- CSV/Excel recipient upload via UI.
- Integration with CRM (HubSpot, Salesforce).

---

## 15. Operational Runbook

### Starting the App
```bash
cd c:/Users/Vansh/ken-email-sender
python app.py
```
Look for: `[OK] Ken Research Email Campaign App running on http://localhost:5000`.

### Stopping the App
- Foreground: `Ctrl+C` in the terminal.
- Background: `Stop-Process -Name python -Force` (PowerShell).

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Site cannot be reached" from team | Wrong IP or AP isolation | Verify IP via `ipconfig`; consider Render deployment |
| "Failed to send email. Check credentials" | `.env` missing or wrong | Verify `.env` has all `ACCOUNT_*` keys |
| Sent count = 0 but opens recorded | Old bug (now fixed) — empty `send_details` | Should not occur after `f1924c7` commit |
| Dashboard shows 300% open rate | Stale opens from deleted campaigns | Clear `email_opens.db` |
| Pending campaign not resuming | App was killed | Check console for `[AUTO-RESUME]` log on next start |
| Pixel not firing | Tracker URL wrong or unreachable | Inspect `<img>` URL in email source; test directly |

### Clearing Data (Reset)
```bash
# Delete all campaigns
Remove-Item -Recurse -Force campaigns/*

# Clear opens database
python -c "import sqlite3; c=sqlite3.connect('email_opens.db'); c.execute('DELETE FROM opens'); c.commit(); c.close()"
```

### Backup Recommendations
- `email_opens.db` — back up before any database operations.
- `campaigns/` folder — back up before mass deletion.
- `.env` — store in a password manager; never commit.

---

## 16. References

- **GitHub Repo:** https://github.com/vanshmeenaken/ABM-Email-Campaign-Automation
- **Microsoft Graph API — sendMail:** https://learn.microsoft.com/en-us/graph/api/user-sendmail
- **Azure AD Client Credentials Flow:** https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-client-creds-grant-flow
- **Flask Docs:** https://flask.palletsprojects.com/
- **Tailwind CSS (CDN):** https://tailwindcss.com/docs/installation/play-cdn

---

## 17. Glossary

| Term | Definition |
|------|------------|
| **Satellite Account** | One of the 4 Azure AD app registrations used to send email on behalf of a real mailbox |
| **Tracking Pixel** | 1x1 transparent PNG embedded in HTML email; loading it triggers an HTTP GET that records the open |
| **Campaign** | A folder under `campaigns/` containing brief, progress, recipients, and log for a single send |
| **Bulk Send Worker** | Background daemon thread that processes recipients with 4-5 min random delays |
| **Auto-Resume** | Startup routine that finds pending campaigns and restarts their bulk workers |
| **Send Details** | Per-recipient status records inside `progress.json` |
| **Open Rate** | `(opens / sent) * 100%` for a given campaign |
| **AP Isolation** | A WiFi setting that prevents devices on the same network from communicating with each other |

---

**End of PRD**
