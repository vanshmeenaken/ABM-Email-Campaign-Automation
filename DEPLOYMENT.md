# Email Tracker Deployment Guide

## Overview

email_tracker.py is a Flask app that tracks email opens via pixel tracking. Deploy to production to capture opens from real email clients.

---

## LOCAL TESTING

```bash
# Install deps
pip install -r requirements.txt

# Run locally
python email_tracker.py

# Test endpoints
curl http://localhost:5000/health
curl "http://localhost:5000/track/pixel?campaign_id=test1&recipient=user@example.com&step=1"
curl "http://localhost:5000/api/opens?campaign_id=test1"
```

Database: `email_opens.db` (local SQLite)

---

## DEPLOY TO RENDER (Recommended - Free Tier)

### 1. Push to GitHub

```bash
git add .
git commit -m "Add email tracker deployment"
git push origin main
```

### 2. Create Render Service

- Go to https://render.com
- New → Web Service
- Connect GitHub repo
- Settings:
  - **Name:** ken-email-tracker
  - **Environment:** Python 3
  - **Build command:** `pip install -r requirements.txt`
  - **Start command:** `gunicorn email_tracker:app`
  - **Plan:** Free (tier) - starts/stops after 15 min inactivity

### 3. Environment Variables

In Render dashboard → Environment:
```
PORT=5000
```

### 4. Deploy

Push to GitHub → Render auto-deploys.

**Output URL:** `https://ken-email-tracker.onrender.com` (example)

---

## DEPLOY TO HEROKU

### 1. Install Heroku CLI

```bash
# macOS/Linux
brew install heroku

# Windows - download from https://devcenter.heroku.com/articles/heroku-cli
```

### 2. Login & Create App

```bash
heroku login
heroku create ken-email-tracker
```

### 3. Deploy

```bash
git push heroku main
```

### 4. View Logs

```bash
heroku logs --tail
```

**Output URL:** `https://ken-email-tracker.herokuapp.com` (example)

---

## UPDATE send_email.py FOR PRODUCTION

After deployment, update `send_email.py` to use production tracker URL:

```python
tracker_url = "https://ken-email-tracker.onrender.com"
# OR
tracker_url = "https://ken-email-tracker.herokuapp.com"
```

Then send emails with tracking:

```bash
python send_email.py \
  --account=1 \
  --to=recipient@example.com \
  --campaign=campaign_123 \
  --tracker-url=https://ken-email-tracker.onrender.com
```

---

## UPDATE campaign_manager.py FOR PRODUCTION

Query opens from production:

```bash
python campaign_manager.py opens campaign_123 https://ken-email-tracker.onrender.com
```

---

## DATABASE PERSISTENCE

**Render:** SQLite database is ephemeral (deleted on redeploy)
- **Solution:** Use Render PostgreSQL addon OR sync data to persistent storage

**Heroku:** Same issue
- **Solution:** Use Heroku Postgres addon

### Add PostgreSQL (Optional)

For persistent tracking data, upgrade to PostgreSQL:

```bash
# Render: Add PostgreSQL from dashboard

# Heroku:
heroku addons:create heroku-postgresql:hobby-dev
```

Then modify `email_tracker.py` to use Postgres connection string instead of SQLite.

---

## MONITORING

- **Render:** https://render.com/dashboard
- **Heroku:** https://dashboard.heroku.com

Check:
- App status (running/stopped)
- Logs for errors
- Request count

---

## TROUBLESHOOTING

**App won't start:**
```bash
# Render logs
curl https://api.render.com/v1/services/<service_id>/logs

# Heroku logs
heroku logs --tail
```

**Tracker not receiving requests:**
- Check tracker URL is correct in send_email.py
- Verify app is running (Render dashboard status)
- Check firewall/CORS (should be open)

**Database growing:**
- SQLite will fill up on free tier → upgrade to Postgres

---

## COSTS

- **Render Free:** $0 (limited resources, auto-stops after 15 min)
- **Render Standard:** ~$7/mo (always-on)
- **Heroku Free:** Free tier discontinued (was $0)
- **Heroku Paid:** ~$7/mo (Eco)
- **PostgreSQL:** ~$9/mo (Render/Heroku)

Recommendation: Start with Render Free, upgrade to Standard + Postgres when in production.
