# Email Tracker - Quick Start Guide

## 1. LOCAL SETUP

```bash
# Install dependencies
pip install -r requirements.txt

# Start tracker server (Terminal 1)
python email_tracker.py

# Test in Terminal 2
curl http://localhost:5000/health
```

## 2. SEND TRACKED EMAIL

```bash
python send_email.py \
  --account=1 \
  --to=your.email@example.com \
  --campaign=test_campaign_1 \
  --subject="Test Email with Tracking"
```

## 3. CHECK OPENS

```bash
# Query tracker directly
curl "http://localhost:5000/api/opens?campaign_id=test_campaign_1"

# Or via campaign manager
python campaign_manager.py opens test_campaign_1
```

---

## PRODUCTION DEPLOYMENT

### Option A: Render (Recommended)

1. Push to GitHub
2. Go to https://render.com → New Web Service
3. Select repo, set:
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn email_tracker:app`
4. Deploy
5. Get URL: `https://ken-email-tracker.onrender.com`

### Option B: Heroku

```bash
heroku login
heroku create ken-email-tracker
git push heroku main
heroku open
```

Get URL: `https://ken-email-tracker.herokuapp.com`

---

## UPDATE PRODUCTION URL

Edit send_email.py or use:

```bash
python send_email.py \
  --account=1 \
  --to=recipient@example.com \
  --campaign=prod_campaign_1 \
  --tracker-url=https://ken-email-tracker.onrender.com
```

---

## DATABASE

- **Local:** `email_opens.db` (SQLite)
- **Production:** Ephemeral (lost on redeploy)
  - Solution: Add PostgreSQL addon (Render/Heroku ~$9/mo)

---

## FILES

| File | Purpose |
|------|---------|
| email_tracker.py | Flask pixel tracking app |
| send_email.py | Send emails with embedded pixel |
| campaign_manager.py | Manage campaigns + query opens |
| requirements.txt | Python dependencies |
| config.py | Environment config |
| .env.example | Template for environment vars |
| render.yaml | Render deployment config |
| Procfile | Heroku deployment config |
| DEPLOYMENT.md | Full deployment guide |

---

## TROUBLESHOOTING

**Pixel not showing opens:**
- Check tracker URL is correct
- Verify Flask app is running
- Check `email_opens.db` exists

**"requests" module not found:**
```bash
pip install requests
```

**Tracker unreachable in production:**
- Check app status on Render/Heroku dashboard
- Check URL is correct
- Check CORS/firewall

---

## NEXT STEPS

1. Test locally
2. Create sample campaign
3. Send tracked email to yourself
4. Verify pixel fires → database records open
5. Deploy to Render/Heroku
6. Test production tracker
7. Update URLs in send_email.py for prod
