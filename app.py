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
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

from flask import Flask, request, send_file, render_template, redirect, url_for, jsonify, flash
from dotenv import load_dotenv

load_dotenv()

# Import send_email from the existing module
from send_email import send_email

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

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

def _save_progress(progress_path, prog):
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(prog, f, indent=2)

def _load_progress(progress_path):
    with open(progress_path, encoding="utf-8") as f:
        return json.load(f)


def parse_recipients(raw_text):
    """Parse recipient lines into dicts.

    Accepted formats (one per line):
      Vansh, Acme Corp, vansh@example.com   <- name + company + email
      Vansh, vansh@example.com              <- name + email
      vansh@example.com                     <- email only
    Returns list of {"email": ..., "first_name": ..., "company": ...}
    """
    result = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line or "@" not in line:
            continue
        parts = [p.strip() for p in line.split(",")]
        email_idx = next((i for i, p in enumerate(parts) if "@" in p), None)
        if email_idx is None:
            continue
        email = parts[email_idx].lower()
        non_email = [p for i, p in enumerate(parts) if i != email_idx]
        first_name = non_email[0] if len(non_email) >= 1 else ""
        company = non_email[1] if len(non_email) >= 2 else ""
        result.append({"email": email, "first_name": first_name, "company": company})
    return result


def personalize(text, first_name, company=""):
    """Replace {First Name}, {Company}, and related placeholders."""
    name = first_name or ""
    comp = company or ""
    for placeholder in ("{First Name}", "{first_name}", "{Name}", "{name}"):
        text = text.replace(placeholder, name)
    for placeholder in ("{Company}", "{company}", "{Company Name}", "{company name}"):
        text = text.replace(placeholder, comp)
    return text


def bulk_send_worker(campaign_id, account_num, recipients, sequences, tracker_url):
    """Multi-step campaign sender with full state persistence.

    State written to progress.json after every action so resume is always safe:
      campaign_status = 'active'  — currently sending step N
      campaign_status = 'waiting' — step N done, sleeping until next_step_send_at
      campaign_status = 'completed' — all steps sent

    On resume: reads next_step_send_at from file; never recalculates from scratch.
    Duplicate-send guard: checks steps_completed per recipient before every send.
    """
    import time, random
    campaign_folder = CAMPAIGNS_DIR / campaign_id
    progress_path = campaign_folder / "progress.json"
    log_path = campaign_folder / "send_log.txt"

    for seq_idx, seq in enumerate(sequences):
        step_num = seq["step"]
        subject = seq["subject"]
        body = seq["body"]
        is_last = (seq_idx == len(sequences) - 1)

        # ── Wait until scheduled send time ──────────────────────────────────
        # next_step_send_at may be pre-written (resume from waiting state)
        # or derived from delay_days on first run.
        try:
            prog = _load_progress(progress_path)
            stored_send_at = prog.get("next_step_send_at") if prog.get("current_step") == step_num else None
        except Exception:
            stored_send_at = None

        if stored_send_at:
            send_at = datetime.fromisoformat(stored_send_at)
        else:
            delay_days = seq.get("delay_days", 0)
            send_at = datetime.now() + timedelta(days=delay_days) if delay_days > 0 else datetime.now()

        remaining = (send_at - datetime.now()).total_seconds()
        if remaining > 0:
            # Persist waiting state so dashboard shows correct status
            try:
                prog = _load_progress(progress_path)
                prog["campaign_status"] = "waiting"
                prog["current_step"] = step_num
                prog["next_step_send_at"] = send_at.isoformat()
                prog["last_update"] = datetime.now().isoformat()
                _save_progress(progress_path, prog)
            except Exception:
                pass

            days_left = remaining / 86400
            print(f"[{campaign_id}] Step {step_num}: waiting {days_left:.1f}d "
                  f"(until {send_at.strftime('%Y-%m-%d %H:%M')})...")
            time.sleep(remaining)

        # ── Mark step as actively sending ────────────────────────────────────
        try:
            prog = _load_progress(progress_path)
            prog["campaign_status"] = "active"
            prog["current_step"] = step_num
            prog["next_step_send_at"] = None
            prog["last_update"] = datetime.now().isoformat()
            _save_progress(progress_path, prog)
        except Exception:
            pass

        # ── Determine which recipients still need this step ──────────────────
        # Duplicate-send guard: read live progress.json, build set of emails
        # that already got this step, then filter recipients list.
        try:
            prog = _load_progress(progress_path)
            already_sent = {
                d["recipient"] for d in prog["send_details"]
                if step_num in d.get("steps_completed", [])
            }
            failed_emails = {
                d["recipient"] for d in prog["send_details"]
                if d.get("status") == "failed"
            }
            replied_emails = {
                d["recipient"] for d in prog["send_details"]
                if d.get("replied")
            }
        except Exception:
            already_sent, failed_emails, replied_emails = set(), set(), set()

        # recipients is a list of {"email": ..., "first_name": ..., "company": ...}
        need_step = [
            r for r in recipients
            if r["email"] not in already_sent
            and r["email"] not in failed_emails
            and r["email"] not in replied_emails
        ]

        print(f"[{campaign_id}] Step {step_num}: sending to {len(need_step)} recipients "
              f"(skipping {len(recipients) - len(need_step)} already sent)...")

        for i, rec in enumerate(need_step):
            email = rec["email"]
            first_name = rec.get("first_name", "")
            company = rec.get("company", "")
            try:
                if i > 0:
                    time.sleep(random.uniform(240, 300))  # 4-5 min anti-spam gap

                # Personalize subject and body for this individual
                p_subject = personalize(subject, first_name, company)
                p_body = personalize(body, first_name, company)

                result = send_email(
                    account_num=account_num,
                    recipient_email=email,
                    subject=p_subject,
                    body=p_body,
                    campaign_id=campaign_id,
                    step=step_num,
                    tracker_url=tracker_url,
                )

                # Update per-recipient state
                try:
                    prog = _load_progress(progress_path)
                    for detail in prog["send_details"]:
                        if detail["recipient"] == email:
                            steps_done = detail.setdefault("steps_completed", [])
                            if result:
                                if step_num not in steps_done:
                                    steps_done.append(step_num)
                                detail["status"] = "sent"
                                detail["step"] = step_num
                                detail["sent_at"] = datetime.now().isoformat()
                                if step_num == 1:
                                    prog["sent"] = prog.get("sent", 0) + 1
                                    prog["pending"] = max(0, prog.get("pending", 1) - 1)
                            else:
                                detail["status"] = "failed"
                                if step_num == 1:
                                    prog["failed"] = prog.get("failed", 0) + 1
                                    prog["pending"] = max(0, prog.get("pending", 1) - 1)
                            break
                    prog["last_update"] = datetime.now().isoformat()
                    _save_progress(progress_path, prog)
                except Exception:
                    pass

                status_str = "SENT" if result else "FAILED"
                with open(log_path, "a", encoding="utf-8") as f:
                    label = f"{first_name} <{email}>" if first_name else email
                    f.write(f"[Step {step_num}] [{status_str}] {label} at {datetime.now()}\n")

            except Exception as e:
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(f"[Step {step_num}] [ERROR] {email} at {datetime.now()}: {e}\n")
                except Exception:
                    pass

        # ── Record step completion ────────────────────────────────────────────
        try:
            prog = _load_progress(progress_path)
            completed_at = prog.setdefault("step_completed_at", {})
            completed_at[str(step_num)] = datetime.now().isoformat()

            if is_last:
                prog["campaign_status"] = "completed"
                prog["next_step_send_at"] = None
                print(f"[{campaign_id}] All {len(sequences)} step(s) complete.")
            else:
                # Pre-calculate when the NEXT step will send and persist it
                next_seq = sequences[seq_idx + 1]
                next_send_at = datetime.now() + timedelta(days=next_seq.get("delay_days", 1))
                prog["campaign_status"] = "waiting"
                prog["current_step"] = next_seq["step"]
                prog["next_step_send_at"] = next_send_at.isoformat()
                print(f"[{campaign_id}] Step {step_num} done. "
                      f"Step {next_seq['step']} scheduled for {next_send_at.strftime('%Y-%m-%d %H:%M')}.")

            prog["last_update"] = datetime.now().isoformat()
            _save_progress(progress_path, prog)
        except Exception:
            pass


def create_bulk_campaign(campaign_id, campaign_name, account_num, recipients, sequences):
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
        "total_steps": len(sequences),
        "email_sequences": sequences,
    }
    with open(campaign_folder / "brief.json", "w", encoding="utf-8") as f:
        json.dump(brief, f, indent=2)

    # recipients = [{"email": ..., "first_name": ..., "company": ...}, ...]
    with open(campaign_folder / "recipients.csv", "w", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["first_name", "company", "email"])
        for r in recipients:
            writer.writerow([r.get("first_name", ""), r.get("company", ""), r["email"]])

    progress = {
        "campaign_id": campaign_id,
        "total_recipients": len(recipients),
        "total_steps": len(sequences),
        "current_step": 1,
        "campaign_status": "active",
        "next_step_send_at": None,
        "step_completed_at": {},
        "sent": 0,
        "pending": len(recipients),
        "failed": 0,
        "retry_queue": 0,
        "last_update": datetime.now().isoformat(),
        "send_details": [
            {
                "recipient": r["email"],
                "first_name": r.get("first_name", ""),
                "company": r.get("company", ""),
                "step": 0,
                "steps_completed": [],
                "status": "pending",
                "message_id": None,
                "sent_at": None,
                "retry_count": 0,
            }
            for r in recipients
        ],
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
    all_recent_replies = []
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
                campaign_status = progress.get("campaign_status", "active")
                next_send_at = progress.get("next_step_send_at")
                next_send_label = None
                if campaign_status == "waiting" and next_send_at:
                    try:
                        dt = datetime.fromisoformat(next_send_at)
                        delta = dt - datetime.now()
                        if delta.total_seconds() > 0:
                            hrs = int(delta.total_seconds() // 3600)
                            if hrs >= 24:
                                next_send_label = f"in {hrs // 24}d {hrs % 24}h"
                            else:
                                next_send_label = f"in {hrs}h"
                        else:
                            next_send_label = "due now"
                    except Exception:
                        next_send_label = "soon"

                # Replied count + collect recent replies
                replied_count = 0
                for d in progress.get("send_details", []):
                    if d.get("replied"):
                        replied_count += 1
                        all_recent_replies.append({
                            "recipient": d["recipient"],
                            "first_name": d.get("first_name", ""),
                            "campaign_id": folder.name,
                            "campaign_name": brief.get("name", folder.name),
                            "replied_at": d.get("replied_at", ""),
                            "reply_preview": d.get("reply_preview", ""),
                            "reply_subject": d.get("reply_subject", ""),
                        })

                campaigns_info.append({
                    "id": folder.name,
                    "name": brief.get("name", folder.name),
                    "account": brief.get("account_name", "—"),
                    "status": brief.get("status", "active"),
                    "campaign_status": campaign_status,
                    "next_step_send_at": next_send_at,
                    "next_send_label": next_send_label,
                    "sent": sent,
                    "total_recipients": progress.get("total_recipients", 0),
                    "pending": progress.get("pending", 0),
                    "opens": opens_for_campaign,
                    "open_rate": open_rate,
                    "replied": replied_count,
                    "total_steps": brief.get("total_steps", 1),
                    "current_step": progress.get("current_step", 1),
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

    all_recent_replies.sort(key=lambda x: x["replied_at"], reverse=True)

    return {
        "total_campaigns": len(campaigns_info),
        "total_sent": total_sent,
        "total_opens": total_opens,
        "avg_open_rate": avg_open_rate,
        "campaigns": campaigns_info,
        "recent_opens": [dict(r) for r in recent_opens],
        "recent_replies": all_recent_replies[:10],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    stats = get_dashboard_stats()
    return render_template("dashboard.html", **stats)


def get_tracker_url():
    """Get tracker URL — Render URL > env var > network IP > localhost."""
    # On Render, use the public service URL
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    if render_url:
        return render_url
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
    campaign_id = request.form.get("campaign_id", "").strip() or None
    tracker_url = request.form.get("tracker_url", "http://localhost:5000").strip()

    if not account_num or account_num not in ACCOUNTS:
        flash("Please select a valid account.", "error")
        return redirect(url_for("send_form"))
    if not recipients_raw:
        flash("At least one recipient email is required.", "error")
        return redirect(url_for("send_form"))

    recipients = parse_recipients(recipients_raw)
    if not recipients:
        flash("No valid email addresses found in recipients field.", "error")
        return redirect(url_for("send_form"))

    # Build sequences from form (up to 3 steps)
    sequences = []
    subject_1 = request.form.get("subject_1", "").strip() or "Ken Research Outreach"
    body_1 = request.form.get("body_1", "").strip() or (
        f"<p>This is an outreach email from Ken Research.</p>"
        f"<p>Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"
    )
    sequences.append({"step": 1, "delay_days": 0, "subject": subject_1, "body": body_1})

    for step_num in [2, 3]:
        subj = request.form.get(f"subject_{step_num}", "").strip()
        bod = request.form.get(f"body_{step_num}", "").strip()
        if subj or bod:
            try:
                delay = max(1, int(request.form.get(f"delay_days_{step_num}", "2") or "2"))
            except (ValueError, TypeError):
                delay = 2
            sequences.append({
                "step": step_num,
                "delay_days": delay,
                "subject": subj or subject_1,
                "body": bod or body_1,
            })

    if not campaign_id:
        campaign_id = f"camp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    n_steps = len(sequences)
    campaign_label = sequences[0]["subject"]

    try:
        create_bulk_campaign(campaign_id, campaign_label, account_num, recipients, sequences)
        thread = threading.Thread(
            target=bulk_send_worker,
            args=(campaign_id, account_num, recipients, sequences, tracker_url),
            daemon=True,
        )
        thread.start()

        step_summary = f"{n_steps}-step series" if n_steps > 1 else "1 message"
        named = sum(1 for r in recipients if r.get("first_name") or r.get("company"))
        personalized = f" ({named} personalized)" if named else ""
        flash(
            f"Campaign started: {len(recipients)} recipient(s){personalized}, {step_summary}, "
            f"from {ACCOUNTS[account_num]}. 4-5 min gap between emails. "
            f"Watch Dashboard for live progress.",
            "success",
        )
    except Exception as e:
        flash(f"Error starting campaign: {str(e)}", "error")

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
    """Resume a campaign from its persisted state.

    Safe against duplicates: uses steps_completed per recipient.
    Safe against early sends: respects next_step_send_at unless user explicitly clicks Resume.
    Manual Resume = user override; skips remaining wait and sends immediately.
    """
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

        progress = _load_progress(progress_path)
        with open(brief_path, encoding="utf-8") as f:
            brief = json.load(f)

        campaign_status = progress.get("campaign_status", "active")
        if campaign_status == "completed":
            flash("Campaign already completed — all steps sent.", "error")
            return redirect(url_for("dashboard"))

        current_step = progress.get("current_step", 1)
        all_sequences = brief.get("email_sequences", [])

        # Recipients who still need the current step (duplicate-send guard)
        pending_recipients = [
            {"email": d["recipient"], "first_name": d.get("first_name", ""), "company": d.get("company", "")}
            for d in progress.get("send_details", [])
            if current_step not in d.get("steps_completed", []) and d.get("status") != "failed"
        ]
        # Fallback for old-format campaigns
        if not pending_recipients:
            pending_recipients = [
                {"email": d["recipient"], "first_name": d.get("first_name", ""), "company": d.get("company", "")}
                for d in progress.get("send_details", [])
                if d.get("status") == "pending"
            ]

        if not pending_recipients:
            flash(f"No pending recipients for Step {current_step}.", "error")
            return redirect(url_for("dashboard"))

        account_num = brief.get("account_number", "1")
        tracker_url = get_tracker_url()

        # Build remaining sequences from current_step onward
        remaining = [s for s in all_sequences if s["step"] >= current_step]
        if not remaining:
            remaining = all_sequences

        # Manual Resume = send current step NOW, no delay
        # Strip next_step_send_at so worker sends immediately
        remaining = [dict(remaining[0], delay_days=0)] + remaining[1:]

        # Clear waiting state so dashboard updates immediately
        progress["campaign_status"] = "active"
        progress["next_step_send_at"] = None
        progress["last_update"] = datetime.now().isoformat()
        _save_progress(progress_path, progress)

        thread = threading.Thread(
            target=bulk_send_worker,
            args=(campaign_id, account_num, pending_recipients, remaining, tracker_url),
            daemon=True,
        )
        thread.start()

        if campaign_status == "waiting":
            flash(f"'{campaign_id}': Step {current_step} sending now "
                  f"({len(pending_recipients)} recipients) — scheduled wait overridden.", "success")
        else:
            flash(f"'{campaign_id}': Resumed Step {current_step} "
                  f"({len(pending_recipients)} pending recipients).", "success")

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

def reply_checker_worker():
    """Background thread: polls sender inboxes every 10 min for replies from campaign recipients.

    When a reply is found:
    - Sets replied=True, replied_at, reply_preview on the recipient in progress.json
    - bulk_send_worker skips replied recipients automatically on next step
    """
    import time
    from send_email import read_inbox

    while True:
        time.sleep(60)  # 60 seconds between each check
        if not CAMPAIGNS_DIR.exists():
            continue

        for folder in CAMPAIGNS_DIR.iterdir():
            if not folder.is_dir():
                continue
            progress_path = folder / "progress.json"
            brief_path = folder / "brief.json"
            if not (progress_path.exists() and brief_path.exists()):
                continue
            try:
                progress = _load_progress(progress_path)
                if progress.get("campaign_status") == "completed":
                    continue

                with open(brief_path, encoding="utf-8") as f:
                    brief = json.load(f)

                account_num = brief.get("account_number", "1")
                try:
                    since_dt = datetime.fromisoformat(brief.get("created_at", ""))
                except Exception:
                    since_dt = None

                # Only check recipients who haven't replied and aren't failed
                unreplied = {
                    d["recipient"]
                    for d in progress.get("send_details", [])
                    if not d.get("replied") and d.get("status") != "failed"
                }
                if not unreplied:
                    continue

                messages = read_inbox(account_num, since_dt)
                updated = False
                for msg in messages:
                    from_email = msg["from_email"]
                    if from_email not in unreplied:
                        continue
                    for detail in progress["send_details"]:
                        if detail["recipient"] == from_email and not detail.get("replied"):
                            detail["replied"] = True
                            detail["replied_at"] = msg["received_at"]
                            detail["reply_preview"] = msg["body_preview"]
                            detail["reply_subject"] = msg["subject"]
                            updated = True
                            print(f"[REPLY] {folder.name}: reply from {from_email} at {msg['received_at']}")
                            break

                if updated:
                    progress["last_update"] = datetime.now().isoformat()
                    _save_progress(progress_path, progress)

            except Exception as e:
                print(f"[REPLY CHECK ERROR] {folder.name}: {e}")


def auto_resume_pending_campaigns():
    """On startup, resume active/waiting campaigns from their persisted state.

    active  — app was stopped mid-send: resume current step immediately.
    waiting — app was stopped between steps: sleep until next_step_send_at,
              then send. Respects the scheduled delay so no premature sends.
    completed — skip entirely.
    """
    if not CAMPAIGNS_DIR.exists():
        return
    resumed = 0
    for folder in CAMPAIGNS_DIR.iterdir():
        if not folder.is_dir():
            continue
        progress_path = folder / "progress.json"
        brief_path = folder / "brief.json"
        if not (progress_path.exists() and brief_path.exists()):
            continue
        try:
            progress = _load_progress(progress_path)
            with open(brief_path, encoding="utf-8") as f:
                brief = json.load(f)

            campaign_status = progress.get("campaign_status", "active")
            if campaign_status == "completed":
                continue

            current_step = progress.get("current_step", 1)
            all_sequences = brief.get("email_sequences", [])

            # Recipients who still need the current step
            pending = [
                {"email": d["recipient"], "first_name": d.get("first_name", ""), "company": d.get("company", "")}
                for d in progress.get("send_details", [])
                if current_step not in d.get("steps_completed", []) and d.get("status") != "failed"
            ]
            # Fallback for old-format campaigns
            if not pending:
                pending = [
                    {"email": d["recipient"], "first_name": d.get("first_name", ""), "company": d.get("company", "")}
                    for d in progress.get("send_details", [])
                    if d.get("status") == "pending"
                ]
            if not pending:
                continue

            account_num = brief.get("account_number", "1")
            tracker_url = get_tracker_url()
            remaining_seqs = [s for s in all_sequences if s["step"] >= current_step]
            if not remaining_seqs:
                remaining_seqs = all_sequences

            if campaign_status == "waiting":
                # Preserve the scheduled send time — worker will sleep until then.
                # next_step_send_at is already in progress.json; worker reads it.
                next_send_at = progress.get("next_step_send_at", "")
                try:
                    dt = datetime.fromisoformat(next_send_at)
                    label = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    label = "scheduled time"
                print(f"[AUTO-RESUME] {folder.name}: Step {current_step} waiting until {label}, "
                      f"{len(pending)} recipients queued.")
            else:
                # Active but interrupted — send current step immediately (no delay)
                remaining_seqs = [dict(remaining_seqs[0], delay_days=0)] + remaining_seqs[1:]
                print(f"[AUTO-RESUME] {folder.name}: Step {current_step} active, "
                      f"resuming {len(pending)} recipients immediately.")

            thread = threading.Thread(
                target=bulk_send_worker,
                args=(folder.name, account_num, pending, remaining_seqs, tracker_url),
                daemon=True,
            )
            thread.start()
            resumed += 1

        except Exception as e:
            print(f"[AUTO-RESUME ERROR] {folder.name}: {e}")
    if resumed:
        print(f"[OK] Auto-resumed {resumed} campaign(s)")


# Run on startup regardless of whether launched via Python or gunicorn
init_db()
auto_resume_pending_campaigns()
threading.Thread(target=reply_checker_worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    print(f"[OK] Ken Research Email Campaign App running on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
