#!/usr/bin/env python3
"""
Ken Research - Email Campaign Web App
Unified Flask app combining email sending, tracking, and campaign dashboard.
"""

import sqlite3
import os
import csv
import json
import socket
import threading
from datetime import datetime
from io import BytesIO
from pathlib import Path

from flask import Flask, request, send_file, render_template, redirect, url_for, jsonify, flash
from dotenv import load_dotenv

load_dotenv()

# Import send_email from the existing module
from send_email import send_email

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "ken-research-secret-2024")

DB_PATH = Path(__file__).parent / "email_opens.db"
CAMPAIGNS_DIR = Path(__file__).parent / "campaigns"

# 1x1 transparent PNG pixel
PIXEL = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
    b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)

ACCOUNTS = {
    "1": "Alina Khan",
    "2": "Archita Singh",
    "3": "Sneha Malhotra",
    "4": "Tanushree Kalita",
}

def bulk_send_worker(campaign_id, account_num, recipients, subject, body, tracker_url, delay_seconds=10):
    """Send emails to all recipients with a short delay between each. Runs in background thread."""
    import time
    campaign_folder = CAMPAIGNS_DIR / campaign_id

    for i, recipient in enumerate(recipients):
        try:
            if i > 0:
                time.sleep(delay_seconds)

            result = send_email(
                account_num=account_num,
                recipient_email=recipient,
                subject=subject,
                body=body,
                campaign_id=campaign_id,
                step=1,
                tracker_url=tracker_url,
            )

            # Update progress.json after each send
            progress_path = campaign_folder / "progress.json"
            if progress_path.exists():
                with open(progress_path, encoding="utf-8") as f:
                    progress = json.load(f)

                for detail in progress["send_details"]:
                    if detail["recipient"] == recipient and detail["status"] == "pending":
                        if result:
                            detail["status"] = "sent"
                            detail["step"] = 1
                            detail["sent_at"] = datetime.now().isoformat()
                            progress["sent"] += 1
                            progress["pending"] -= 1
                        else:
                            detail["status"] = "failed"
                            progress["failed"] += 1
                            progress["pending"] -= 1
                        break

                progress["last_update"] = datetime.now().isoformat()
                with open(progress_path, "w", encoding="utf-8") as f:
                    json.dump(progress, f, indent=2)

            # Append to log
            log_path = campaign_folder / "send_log.txt"
            status = "SENT" if result else "FAILED"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{status}] {recipient} at {datetime.now()}\n")

        except Exception as e:
            log_path = campaign_folder / "send_log.txt"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[ERROR] {recipient} at {datetime.now()}: {str(e)}\n")


def create_bulk_campaign(campaign_id, campaign_name, account_num, recipients, subject, body):
    """Create campaign folder structure for bulk send + scheduler"""
    campaign_folder = CAMPAIGNS_DIR / campaign_id
    campaign_folder.mkdir(parents=True, exist_ok=True)

    brief = {
        "campaign_id": campaign_id,
        "name": campaign_name,
        "account_number": account_num,
        "account_name": ACCOUNTS[account_num],
        "created_at": datetime.now().isoformat(),
        "status": "active",
        "total_recipients": len(recipients),
        "email_sequences": [{"step": 1, "delay_days": 0, "delay_minutes": 0, "subject": subject, "body": body}]
    }
    with open(campaign_folder / "brief.json", "w", encoding="utf-8") as f:
        json.dump(brief, f, indent=2)

    with open(campaign_folder / "recipients.csv", "w", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["email"])
        for r in recipients:
            writer.writerow([r])

    progress = {
        "campaign_id": campaign_id,
        "total_recipients": len(recipients),
        "sent": 0,
        "pending": len(recipients),
        "failed": 0,
        "retry_queue": 0,
        "last_update": datetime.now().isoformat(),
        "current_step": 1,
        "send_details": [
            {
                "recipient": r,
                "step": 0,
                "status": "pending",
                "message_id": None,
                "sent_at": None,
                "retry_count": 0
            }
            for r in recipients
        ]
    }
    with open(campaign_folder / "progress.json", "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)

    with open(campaign_folder / "send_log.txt", "w", encoding="utf-8") as f:
        f.write(f"Campaign: {campaign_name}\nAccount: {ACCOUNTS[account_num]}\nRecipients: {len(recipients)}\nCreated: {datetime.now()}\n{'='*60}\n\n")

    return campaign_id


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def init_db():
    """Initialize email_opens.db on startup."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS opens (
            id INTEGER PRIMARY KEY,
            campaign_id TEXT,
            recipient TEXT,
            step INTEGER,
            timestamp TEXT,
            user_agent TEXT,
            ip_address TEXT
        )
    ''')
    conn.commit()
    conn.close()


def query_db(sql, params=(), one=False):
    """Run a read query and return rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()
    return (rows[0] if rows else None) if one else rows


def execute_db(sql, params=()):
    """Run a write query."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(sql, params)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------

def get_dashboard_stats():
    """Aggregate stats from opens table and campaigns folder."""
    # Opens stats from DB
    campaign_rows = query_db('''
        SELECT
            campaign_id,
            COUNT(*) as open_count,
            MAX(timestamp) as last_open
        FROM opens
        GROUP BY campaign_id
        ORDER BY last_open DESC
    ''')

    recent_opens = query_db('''
        SELECT campaign_id, recipient, step, timestamp
        FROM opens
        ORDER BY timestamp DESC
        LIMIT 10
    ''')

    # Campaign folder stats
    campaigns_info = []
    total_sent = 0
    if CAMPAIGNS_DIR.exists():
        for folder in sorted(CAMPAIGNS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not folder.is_dir():
                continue
            brief_path = folder / "brief.json"
            progress_path = folder / "progress.json"
            if brief_path.exists() and progress_path.exists():
                import json
                with open(brief_path) as f:
                    brief = json.load(f)
                with open(progress_path) as f:
                    progress = json.load(f)
                sent = progress.get("sent", 0)
                total_sent += sent
                # Match opens from DB
                opens_for_campaign = next(
                    (r["open_count"] for r in campaign_rows if r["campaign_id"] == folder.name),
                    0
                )
                open_rate = (
                    f"{opens_for_campaign / sent * 100:.1f}%"
                    if sent > 0 else "—"
                )
                campaigns_info.append({
                    "id": folder.name,
                    "name": brief.get("name", folder.name),
                    "account": brief.get("account_name", "—"),
                    "status": brief.get("status", "active"),
                    "sent": sent,
                    "total_recipients": progress.get("total_recipients", 0),
                    "pending": progress.get("pending", 0),
                    "opens": opens_for_campaign,
                    "open_rate": open_rate,
                    "last_open": next(
                        (r["last_open"] for r in campaign_rows if r["campaign_id"] == folder.name),
                        None
                    ),
                })

    # Only count opens for campaigns that exist in campaigns folder
    existing_ids = {c["id"] for c in campaigns_info}
    total_opens = sum(r["open_count"] for r in campaign_rows if r["campaign_id"] in existing_ids)
    avg_open_rate = (
        f"{total_opens / total_sent * 100:.1f}%"
        if total_sent > 0 else "—"
    )

    return {
        "total_campaigns": len(campaigns_info),
        "total_sent": total_sent,
        "total_opens": total_opens,
        "avg_open_rate": avg_open_rate,
        "campaigns": campaigns_info,
        "recent_opens": [dict(r) for r in recent_opens],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    stats = get_dashboard_stats()
    return render_template("dashboard.html", **stats)


def get_tracker_url():
    """Get tracker URL — env var takes priority, else auto-detect network IP."""
    env_url = os.getenv("TRACKER_URL", "").strip()
    if env_url:
        return env_url
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"http://{ip}:5000"
    except Exception:
        return "http://localhost:5000"


@app.route("/send", methods=["GET"])
def send_form():
    suggested_campaign_id = f"camp_{datetime.now().strftime('%Y%m%d_%H%M')}"
    tracker_url = get_tracker_url()
    return render_template(
        "send.html",
        accounts=ACCOUNTS,
        suggested_campaign_id=suggested_campaign_id,
        tracker_url=tracker_url,
    )


@app.route("/send", methods=["POST"])
def send_submit():
    account_num = request.form.get("account", "").strip()
    recipients_raw = request.form.get("recipients", "").strip()
    subject = request.form.get("subject", "").strip() or "Test Email - Ken Research Automation"
    body = request.form.get("body", "").strip()
    campaign_id = request.form.get("campaign_id", "").strip() or None
    tracker_url = request.form.get("tracker_url", "http://localhost:5000").strip()

    if not account_num or account_num not in ACCOUNTS:
        flash("Please select a valid account.", "error")
        return redirect(url_for("send_form"))
    if not recipients_raw:
        flash("At least one recipient email is required.", "error")
        return redirect(url_for("send_form"))

    # Parse recipients (one per line)
    recipients = [r.strip() for r in recipients_raw.splitlines() if r.strip()]

    if not body:
        body = (
            f"<p>This is a test email sent from the Ken Research Email Campaign system.</p>"
            f"<p>Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"
        )

    # SINGLE recipient — send immediately + create campaign record for stats
    if len(recipients) == 1:
        if not campaign_id:
            campaign_id = f"camp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            create_bulk_campaign(campaign_id, subject, account_num, recipients, subject, body)
            result = send_email(
                account_num=account_num,
                recipient_email=recipients[0],
                subject=subject,
                body=body,
                campaign_id=campaign_id,
                step=1,
                tracker_url=tracker_url,
            )
            # Update campaign progress
            progress_path = CAMPAIGNS_DIR / campaign_id / "progress.json"
            with open(progress_path, encoding="utf-8") as f:
                progress = json.load(f)
            for detail in progress["send_details"]:
                if detail["recipient"] == recipients[0]:
                    detail["status"] = "sent" if result else "failed"
                    detail["step"] = 1
                    detail["sent_at"] = datetime.now().isoformat()
                    break
            if result:
                progress["sent"] = 1
                progress["pending"] = 0
            else:
                progress["failed"] = 1
                progress["pending"] = 0
            progress["last_update"] = datetime.now().isoformat()
            with open(progress_path, "w", encoding="utf-8") as f:
                json.dump(progress, f, indent=2)

            if result:
                flash(f"Email sent from {ACCOUNTS[account_num]} to {recipients[0]}. Campaign '{campaign_id}' added to stats.", "success")
            else:
                flash("Failed to send email. Check your credentials and try again.", "error")
        except Exception as e:
            flash(f"Error: {str(e)}", "error")
        return redirect(url_for("send_form"))

    # BULK recipients — create campaign + send in background thread (10 sec between each)
    if not campaign_id:
        campaign_id = f"camp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        create_bulk_campaign(campaign_id, subject, account_num, recipients, subject, body)
        thread = threading.Thread(
            target=bulk_send_worker,
            args=(campaign_id, account_num, recipients, subject, body, tracker_url),
            daemon=True
        )
        thread.start()
        flash(
            f"Bulk send started: {len(recipients)} emails from {ACCOUNTS[account_num]}. "
            f"Sending now with 10 sec between each. Watch Campaign Stats for live progress.",
            "success",
        )
    except Exception as e:
        flash(f"Error starting bulk send: {str(e)}", "error")

    return redirect(url_for("send_form"))


# ---------------------------------------------------------------------------
# Tracking routes (mirrored from email_tracker.py)
# ---------------------------------------------------------------------------

@app.route("/track/pixel", methods=["GET"])
def track_pixel():
    """Receive pixel request and log open."""
    campaign_id = request.args.get("campaign_id", "unknown")
    recipient = request.args.get("recipient", "unknown")
    step = request.args.get("step", "0")
    user_agent = request.headers.get("User-Agent", "")
    ip_address = request.remote_addr
    timestamp = datetime.utcnow().isoformat()

    execute_db(
        '''INSERT INTO opens (campaign_id, recipient, step, timestamp, user_agent, ip_address)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (campaign_id, recipient, int(step), timestamp, user_agent, ip_address),
    )

    return send_file(BytesIO(PIXEL), mimetype="image/png")


@app.route("/api/opens", methods=["GET"])
def get_opens():
    """Query opens, optionally filtered by campaign_id and since timestamp."""
    campaign_id = request.args.get("campaign_id", "")
    since = request.args.get("since", "2000-01-01T00:00:00")

    if campaign_id:
        rows = query_db(
            '''SELECT campaign_id, recipient, step, timestamp, user_agent, ip_address
               FROM opens
               WHERE campaign_id = ? AND timestamp > ?
               ORDER BY timestamp DESC''',
            (campaign_id, since),
        )
    else:
        rows = query_db(
            '''SELECT campaign_id, recipient, step, timestamp, user_agent, ip_address
               FROM opens
               WHERE timestamp > ?
               ORDER BY timestamp DESC''',
            (since,),
        )

    opens = [
        {
            "campaign_id": row["campaign_id"],
            "recipient": row["recipient"],
            "step": row["step"],
            "timestamp": row["timestamp"],
            "user_agent": row["user_agent"],
            "ip_address": row["ip_address"],
        }
        for row in rows
    ]
    return jsonify({"opens": opens, "count": len(opens)})


@app.route("/api/metrics/<campaign_id>", methods=["GET"])
def api_metrics(campaign_id):
    """JSON metrics for a specific campaign."""
    import json

    campaign_folder = CAMPAIGNS_DIR / campaign_id
    brief, progress = {}, {}

    if campaign_folder.exists():
        brief_path = campaign_folder / "brief.json"
        progress_path = campaign_folder / "progress.json"
        if brief_path.exists():
            with open(brief_path) as f:
                brief = json.load(f)
        if progress_path.exists():
            with open(progress_path) as f:
                progress = json.load(f)

    opens_rows = query_db(
        "SELECT COUNT(*) as cnt, MAX(timestamp) as last_open FROM opens WHERE campaign_id = ?",
        (campaign_id,),
        one=True,
    )
    open_count = opens_rows["cnt"] if opens_rows else 0
    last_open = opens_rows["last_open"] if opens_rows else None
    total_sent = progress.get("total_recipients", 0)
    open_rate = f"{open_count / total_sent * 100:.1f}%" if total_sent > 0 else "0%"

    return jsonify({
        "campaign_id": campaign_id,
        "campaign_name": brief.get("name", "Unknown"),
        "account": brief.get("account_name", "Unknown"),
        "created_at": brief.get("created_at", "N/A"),
        "status": brief.get("status", "unknown"),
        "total_sent": total_sent,
        "opens": open_count,
        "open_rate": open_rate,
        "last_open": last_open,
        "pending": progress.get("pending", 0),
        "failed": progress.get("failed", 0),
    })


@app.route("/resume/<campaign_id>", methods=["POST"])
def resume_campaign(campaign_id):
    """Resume a stalled campaign — resend to all pending recipients."""
    try:
        campaign_folder = CAMPAIGNS_DIR / campaign_id
        if not campaign_folder.exists():
            flash(f"Campaign '{campaign_id}' not found.", "error")
            return redirect(url_for("dashboard"))

        progress_path = campaign_folder / "progress.json"
        brief_path = campaign_folder / "brief.json"
        if not progress_path.exists() or not brief_path.exists():
            flash("Campaign data missing.", "error")
            return redirect(url_for("dashboard"))

        with open(progress_path, encoding="utf-8") as f:
            progress = json.load(f)
        with open(brief_path, encoding="utf-8") as f:
            brief = json.load(f)

        pending_recipients = [
            d["recipient"] for d in progress.get("send_details", [])
            if d.get("status") == "pending"
        ]

        if not pending_recipients:
            flash("No pending recipients found.", "error")
            return redirect(url_for("dashboard"))

        account_num = brief.get("account_number", "1")
        subject = brief.get("email_sequences", [{}])[0].get("subject", "Ken Research")
        body = brief.get("email_sequences", [{}])[0].get("body", "")
        tracker_url = os.getenv("TRACKER_URL", "http://localhost:5000")

        thread = threading.Thread(
            target=bulk_send_worker,
            args=(campaign_id, account_num, pending_recipients, subject, body, tracker_url),
            daemon=True
        )
        thread.start()
        flash(f"Resumed '{campaign_id}': sending {len(pending_recipients)} pending emails now.", "success")
    except Exception as e:
        flash(f"Error resuming: {str(e)}", "error")
    return redirect(url_for("dashboard"))


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------

@app.template_filter("friendly_dt")
def friendly_dt(value):
    """Format ISO timestamp to a readable date/time."""
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value.replace("Z", ""))
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        return value


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    print(f"[OK] Ken Research Email Campaign App running on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
