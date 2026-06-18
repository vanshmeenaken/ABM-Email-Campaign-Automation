#!/usr/bin/env python3
"""
Ken Research - Email Campaign Web App
Unified Flask app combining email sending, tracking, and campaign dashboard.
"""

import os
import json
import socket
import threading
from datetime import datetime, timedelta
from io import BytesIO

import psycopg2
import psycopg2.extras
from flask import Flask, request, send_file, render_template, redirect, url_for, jsonify, flash
from dotenv import load_dotenv

load_dotenv()

from send_email import send_email

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

DATABASE_URL = os.getenv("DATABASE_URL")
BOUNCIFY_API_KEY = os.getenv("BOUNCIFY_API_KEY", "")

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

# Prevents duplicate threads running the same campaign simultaneously
_running_campaigns: set = set()
_running_lock = threading.Lock()


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def get_db_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


# ---------------------------------------------------------------------------
# Campaign state helpers (DB-backed, replaces progress.json / brief.json)
# ---------------------------------------------------------------------------

def _save_progress(campaign_id, prog):
    conn = get_db_conn()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE campaigns SET progress = %s WHERE campaign_id = %s",
            (json.dumps(prog), campaign_id),
        )
        conn.commit()
    finally:
        conn.close()


def _load_progress(campaign_id):
    conn = get_db_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT progress FROM campaigns WHERE campaign_id = %s", (campaign_id,))
        row = c.fetchone()
        if row:
            return row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return {}
    finally:
        conn.close()


def _load_brief(campaign_id):
    conn = get_db_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT brief FROM campaigns WHERE campaign_id = %s", (campaign_id,))
        row = c.fetchone()
        if row:
            return row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return {}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Personalization helpers
# ---------------------------------------------------------------------------

def parse_recipients(raw_text):
    """Parse recipient lines into dicts.

    Supports:
    1. Header-aware tab/comma-separated (paste from Excel/Sheets with column headers).
       Recognises columns: Email, Full Name / Name, Company Name / Company, etc.
       Skips rows where the email cell is empty or "NA".
    2. Headerless tab-separated — auto-detects email column by @, heuristically
       picks name and company from remaining text fields.
    3. Simple comma-separated: "Name, Company, email" or "Name, email" or "email".

    Returns list of {"email": ..., "first_name": ..., "company": ...}
    """
    _JUNK = {"na", "n/a", "-", "--", ""}

    def _is_url(s):
        sl = s.lower()
        return s.startswith("http") or "linkedin.com" in sl or (
            "." in s and "/" in s and not "@" in s
        )

    def _is_phone(s):
        stripped = s.replace("+", "").replace(" ", "").replace("-", "")
        return stripped.isdigit() and len(stripped) >= 7

    def _find_col(headers, *keywords):
        for i, h in enumerate(headers):
            if any(k in h.lower() for k in keywords):
                return i
        return None

    lines = [l for l in raw_text.splitlines() if l.strip()]
    if not lines:
        return []

    result = []

    # --- Detect if first line is a header row (no @ in it) ---
    first = lines[0]
    delimiter = "\t" if "\t" in first else ","
    first_parts = [p.strip() for p in first.split(delimiter)]
    has_header = "@" not in first and any(
        kw in first.lower() for kw in ("email", "name", "company", "linkedin")
    )

    if has_header:
        headers = [p.lower().strip() for p in first_parts]
        email_col   = _find_col(headers, "email")
        name_col    = _find_col(headers, "full name", "name", "prospect_full")
        company_col = _find_col(headers, "company name", "company", "prospect_company", "organisation")

        if email_col is None:
            # No email column found in header — fall through to heuristic
            has_header = False
        else:
            for line in lines[1:]:
                parts = [p.strip() for p in line.split(delimiter)]
                # Pad short rows
                while len(parts) <= max(filter(None.__ne__, [email_col, name_col, company_col])):
                    parts.append("")

                email = parts[email_col].strip().lower() if email_col < len(parts) else ""
                if not email or email in _JUNK or "@" not in email:
                    continue  # No email — skip row

                raw_name = parts[name_col].strip() if name_col is not None and name_col < len(parts) else ""
                first_name = raw_name.split()[0] if raw_name else ""

                company = parts[company_col].strip() if company_col is not None and company_col < len(parts) else ""
                if company.lower() in _JUNK:
                    company = ""

                result.append({"email": email, "first_name": first_name, "company": company})
            return result

    # --- Heuristic mode (no header) ---
    for line in lines:
        line = line.strip()
        if not line or "@" not in line:
            continue

        parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split(","))]

        # Find email column
        email_idx = next(
            (i for i, p in enumerate(parts) if "@" in p and not _is_url(p)), None
        )
        if email_idx is None:
            continue

        email = parts[email_idx].lower().strip()
        if email in _JUNK:
            continue

        # Remaining clean text columns
        text_parts = [
            p for i, p in enumerate(parts)
            if i != email_idx
            and p.lower().strip() not in _JUNK
            and not _is_url(p)
            and not _is_phone(p)
        ]

        first_name = text_parts[0].split()[0] if text_parts else ""
        company    = text_parts[1] if len(text_parts) >= 2 else ""

        result.append({"email": email, "first_name": first_name, "company": company})

    return result


def personalize(text, first_name, company=""):
    """Replace {First Name}, [First Name], {Company}, [Company Name], and variants."""
    name = first_name or ""
    comp = company or ""
    for placeholder in ("{First Name}", "{first_name}", "{Name}", "{name}",
                        "[First Name]", "[first name]", "[Name]", "[name]"):
        text = text.replace(placeholder, name)
    for placeholder in ("{Company}", "{company}", "{Company Name}", "{company name}",
                        "[Company]", "[company]", "[Company Name]", "[company name]"):
        text = text.replace(placeholder, comp)
    return text


def plain_to_html(text):
    """Convert plain text body to HTML if it contains no HTML tags."""
    import re
    if re.search(r'<[a-zA-Z/]', text):
        return text  # already HTML, leave untouched
    # Preserve paragraphs and line breaks
    paragraphs = text.split('\n\n')
    parts = []
    for para in paragraphs:
        lines = para.replace('\n', '<br>')
        parts.append(f"<p>{lines}</p>")
    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# Attachment helpers
# ---------------------------------------------------------------------------

def save_attachment(campaign_id, step, filename, content_type, content_b64):
    execute_db(
        """INSERT INTO attachments (campaign_id, step, filename, content_type, content_b64)
           VALUES (%s, %s, %s, %s, %s)""",
        (campaign_id, step, filename, content_type, content_b64),
    )


def get_attachments(campaign_id, step):
    return [dict(r) for r in query_db(
        "SELECT filename, content_type, content_b64 FROM attachments WHERE campaign_id = %s AND step = %s ORDER BY id",
        (campaign_id, step),
    )]


def apply_attachments(body, attachments):
    """Replace {image}/{file} markers in body and build Graph API attachment list.
    Multiple markers supported — each replaced by successive file in order.
    Unmatched files appended at end or attached silently.
    """
    graph_attachments = []
    image_files = [a for a in attachments if a["content_type"].startswith("image/")]
    other_files = [a for a in attachments if not a["content_type"].startswith("image/")]

    img_markers = ["{image}", "[image]", "{Image}", "[Image]"]
    file_markers = ["{file}", "[file]", "{File}", "[File]", "{attachment}", "[attachment]"]

    # Replace image markers
    for idx, att in enumerate(image_files):
        cid = f"img{idx}"
        img_tag = (f'<img src="cid:{cid}" style="max-width:100%;height:auto;display:block;" '
                   f'alt="{att["filename"]}" />')
        replaced = False
        for m in img_markers:
            if m in body:
                body = body.replace(m, img_tag, 1)
                replaced = True
                break
        if not replaced:
            body = body + f"<br>{img_tag}"
        graph_attachments.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": att["filename"],
            "contentType": att["content_type"],
            "contentBytes": att["content_b64"],
            "contentId": cid,
            "isInline": True,
        })

    # Replace file markers (PDF, Excel, etc.)
    for att in other_files:
        file_ref = f'<p style="margin:8px 0;">&#128206; <em>{att["filename"]}</em></p>'
        replaced = False
        for m in file_markers:
            if m in body:
                body = body.replace(m, file_ref, 1)
                replaced = True
                break
        if not replaced:
            body = body + file_ref
        graph_attachments.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": att["filename"],
            "contentType": att["content_type"],
            "contentBytes": att["content_b64"],
            "isInline": False,
        })

    return body, graph_attachments


# ---------------------------------------------------------------------------
# Email validation
# ---------------------------------------------------------------------------

def validate_email_bouncify(email):
    """Validate email via Bouncify. Returns (status, result).
    status: 'valid' | 'invalid' | 'risky' | 'unknown'
    """
    if not BOUNCIFY_API_KEY:
        return "unknown", "no_api_key"
    try:
        import requests as req
        resp = req.get(
            "https://api.bouncify.io/v1/verify",
            params={"apikey": BOUNCIFY_API_KEY, "email": email},
            timeout=15,
        )
        if resp.status_code == 200:
            result = resp.json().get("result", "unknown")
            if result == "deliverable":
                return "valid", result
            elif result == "undeliverable":
                return "invalid", result
            elif result == "risky":
                return "risky", result
            else:
                return "unknown", result
        return "unknown", f"http_{resp.status_code}"
    except Exception:
        return "unknown", "error"


# ---------------------------------------------------------------------------
# Campaign worker
# ---------------------------------------------------------------------------

def bulk_send_worker(campaign_id, account_num, recipients, sequences, tracker_url):
    """Multi-step campaign sender with full state persistence via Supabase."""
    import time, random

    with _running_lock:
        if campaign_id in _running_campaigns:
            print(f"[SKIP] {campaign_id} already running — duplicate thread blocked")
            return
        _running_campaigns.add(campaign_id)

    try:
        for seq_idx, seq in enumerate(sequences):
            step_num = seq["step"]
            subject = seq["subject"]
            body = seq["body"]
            is_last = (seq_idx == len(sequences) - 1)

            # Wait until scheduled send time
            try:
                prog = _load_progress(campaign_id)
                stored_send_at = prog.get("next_step_send_at") if prog.get("current_step") == step_num else None
            except Exception:
                stored_send_at = None

            if stored_send_at:
                send_at = datetime.fromisoformat(stored_send_at)
            else:
                delay_days = seq.get("delay_days", 0)
                delay_minutes = seq.get("delay_minutes", 0)
                total_seconds = delay_days * 86400 + delay_minutes * 60
                send_at = datetime.now() + timedelta(seconds=total_seconds) if total_seconds > 0 else datetime.now()

            remaining = (send_at - datetime.now()).total_seconds()
            if remaining > 0:
                try:
                    prog = _load_progress(campaign_id)
                    prog["campaign_status"] = "waiting"
                    prog["current_step"] = step_num
                    prog["next_step_send_at"] = send_at.isoformat()
                    prog["last_update"] = datetime.now().isoformat()
                    _save_progress(campaign_id, prog)
                except Exception:
                    pass
                print(f"[{campaign_id}] Step {step_num}: waiting {remaining/86400:.1f}d "
                      f"(until {send_at.strftime('%Y-%m-%d %H:%M')})...")
                time.sleep(remaining)

            # Mark step as actively sending
            try:
                prog = _load_progress(campaign_id)
                prog["campaign_status"] = "active"
                prog["current_step"] = step_num
                prog["next_step_send_at"] = None
                prog["last_update"] = datetime.now().isoformat()
                _save_progress(campaign_id, prog)
            except Exception:
                pass

            # Duplicate-send guard + replied guard + skipped guard
            try:
                prog = _load_progress(campaign_id)
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
                skipped_emails = {
                    d["recipient"] for d in prog["send_details"]
                    if d.get("status") == "skipped"
                }
            except Exception:
                already_sent, failed_emails, replied_emails, skipped_emails = set(), set(), set(), set()

            need_step = [
                r for r in recipients
                if r["email"] not in already_sent
                and r["email"] not in failed_emails
                and r["email"] not in replied_emails
                and r["email"] not in skipped_emails
            ]

            print(f"[{campaign_id}] Step {step_num}: sending to {len(need_step)} recipients "
                  f"(skipping {len(recipients) - len(need_step)} already sent/replied)...")

            # Load attachments for this step once (shared across all recipients)
            step_attachments = get_attachments(campaign_id, step_num)

            sends_attempted = 0
            for i, rec in enumerate(need_step):
                email = rec["email"]
                first_name = rec.get("first_name", "")
                company = rec.get("company", "")
                try:
                    # Validate on Step 1 only (uses Bouncify credit once per email)
                    # Skip validation for internal/trusted domains (they reject verification pings)
                    _email_domain = email.split("@")[-1].lower() if "@" in email else ""
                    if step_num == 1 and BOUNCIFY_API_KEY and _email_domain not in INTERNAL_DOMAINS:
                        val_status, val_result = validate_email_bouncify(email)
                        print(f"[VALIDATE] [{val_status.upper()}] {email}: {val_result}")
                        try:
                            prog = _load_progress(campaign_id)
                            for detail in prog["send_details"]:
                                if detail["recipient"] == email:
                                    detail["validation_status"] = val_status
                                    detail["validation_result"] = val_result
                                    if val_status in ("invalid", "risky"):
                                        detail["status"] = "skipped"
                                        prog["pending"] = max(0, prog.get("pending", 1) - 1)
                                    break
                            _save_progress(campaign_id, prog)
                        except Exception:
                            pass
                        if val_status in ("invalid", "risky"):
                            print(f"[VALIDATE] Skipping {email} ({val_status})")
                            continue

                    if sends_attempted > 0:
                        time.sleep(random.uniform(240, 300))  # 4-5 min anti-spam gap
                    sends_attempted += 1

                    p_subject = personalize(subject, first_name, company)
                    p_body = plain_to_html(personalize(body, first_name, company))

                    # Apply attachments — replace markers in body, build graph list
                    if step_attachments:
                        p_body, graph_atts = apply_attachments(p_body, step_attachments)
                    else:
                        graph_atts = []

                    result = send_email(
                        account_num=account_num,
                        recipient_email=email,
                        subject=p_subject,
                        body=p_body,
                        campaign_id=campaign_id,
                        step=step_num,
                        tracker_url=tracker_url,
                        attachments=graph_atts if graph_atts else None,
                    )

                    try:
                        prog = _load_progress(campaign_id)
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
                        _save_progress(campaign_id, prog)
                    except Exception:
                        pass

                    label = f"{first_name} <{email}>" if first_name else email
                    print(f"[Step {step_num}] [{'SENT' if result else 'FAILED'}] {label} at {datetime.now()}")

                except Exception as e:
                    print(f"[Step {step_num}] [ERROR] {email}: {e}")

            # Record step completion
            try:
                prog = _load_progress(campaign_id)
                prog.setdefault("step_completed_at", {})[str(step_num)] = datetime.now().isoformat()

                if is_last:
                    prog["campaign_status"] = "completed"
                    prog["next_step_send_at"] = None
                    print(f"[{campaign_id}] All {len(sequences)} step(s) complete.")
                else:
                    next_seq = sequences[seq_idx + 1]
                    next_delay_secs = next_seq.get("delay_days", 0) * 86400 + next_seq.get("delay_minutes", 0) * 60
                    next_send_at = datetime.now() + timedelta(seconds=next_delay_secs)
                    prog["campaign_status"] = "waiting"
                    prog["current_step"] = next_seq["step"]
                    prog["next_step_send_at"] = next_send_at.isoformat()
                    print(f"[{campaign_id}] Step {step_num} done. "
                          f"Step {next_seq['step']} scheduled for {next_send_at.strftime('%Y-%m-%d %H:%M')}.")

                prog["last_update"] = datetime.now().isoformat()
                _save_progress(campaign_id, prog)
            except Exception:
                pass

    finally:
        with _running_lock:
            _running_campaigns.discard(campaign_id)


def create_bulk_campaign(campaign_id, campaign_name, account_num, recipients, sequences):
    """Create campaign record in Supabase."""
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
        "last_update": datetime.now().isoformat(),
        "send_details": [
            {
                "recipient": r["email"],
                "first_name": r.get("first_name", ""),
                "company": r.get("company", ""),
                "step": 0,
                "steps_completed": [],
                "status": "pending",
                "sent_at": None,
                "retry_count": 0,
            }
            for r in recipients
        ],
    }

    conn = get_db_conn()
    try:
        c = conn.cursor()
        c.execute(
            """INSERT INTO campaigns (campaign_id, brief, progress)
               VALUES (%s, %s, %s)
               ON CONFLICT (campaign_id) DO UPDATE
               SET brief = EXCLUDED.brief, progress = EXCLUDED.progress""",
            (campaign_id, json.dumps(brief), json.dumps(progress)),
        )
        conn.commit()
    finally:
        conn.close()

    return campaign_id


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def init_db():
    """Create tables if they don't exist."""
    conn = get_db_conn()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS opens (
                id SERIAL PRIMARY KEY,
                campaign_id TEXT,
                recipient TEXT,
                step INTEGER,
                timestamp TEXT,
                user_agent TEXT,
                ip_address TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                campaign_id TEXT PRIMARY KEY,
                brief JSONB NOT NULL DEFAULT '{}',
                progress JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS attachments (
                id SERIAL PRIMARY KEY,
                campaign_id TEXT,
                step INTEGER,
                filename TEXT,
                content_type TEXT,
                content_b64 TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()
    finally:
        conn.close()


def query_db(sql, params=(), one=False):
    conn = get_db_conn()
    try:
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute(sql, params)
        rows = c.fetchall()
        return (rows[0] if rows else None) if one else rows
    finally:
        conn.close()


def execute_db(sql, params=()):
    conn = get_db_conn()
    try:
        c = conn.cursor()
        c.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------

def get_dashboard_stats():
    campaign_rows = query_db("""
        SELECT campaign_id, COUNT(DISTINCT recipient) as open_count, MAX(timestamp) as last_open
        FROM opens
        GROUP BY campaign_id
        ORDER BY last_open DESC
    """)

    recent_opens = query_db("""
        SELECT campaign_id, recipient, step, timestamp
        FROM opens
        ORDER BY timestamp DESC
        LIMIT 10
    """)

    all_campaigns = query_db("""
        SELECT campaign_id, brief, progress
        FROM campaigns
        ORDER BY created_at DESC
    """)

    campaigns_info = []
    total_sent = 0
    all_recent_replies = []

    for row in all_campaigns:
        brief = row["brief"] if isinstance(row["brief"], dict) else json.loads(row["brief"])
        progress = row["progress"] if isinstance(row["progress"], dict) else json.loads(row["progress"])
        cid = row["campaign_id"]

        sent = progress.get("sent", 0)
        total_sent += sent

        opens_for_campaign = next(
            (r["open_count"] for r in campaign_rows if r["campaign_id"] == cid), 0
        )
        open_rate = f"{opens_for_campaign / sent * 100:.1f}%" if sent > 0 else "—"

        campaign_status = progress.get("campaign_status", "active")
        next_send_at = progress.get("next_step_send_at")
        next_send_label = None
        if campaign_status == "waiting" and next_send_at:
            try:
                dt = datetime.fromisoformat(next_send_at)
                delta = dt - datetime.now()
                if delta.total_seconds() > 0:
                    total_secs = int(delta.total_seconds())
                    hrs = total_secs // 3600
                    mins = (total_secs % 3600) // 60
                    if hrs >= 24:
                        next_send_label = f"in {hrs // 24}d {hrs % 24}h"
                    elif hrs > 0:
                        next_send_label = f"in {hrs}h {mins}m"
                    else:
                        next_send_label = f"in {mins}m"
                else:
                    next_send_label = "due now"
            except Exception:
                next_send_label = "soon"

        replied_count = 0
        for d in progress.get("send_details", []):
            if d.get("replied"):
                replied_count += 1
                all_recent_replies.append({
                    "recipient": d["recipient"],
                    "first_name": d.get("first_name", ""),
                    "campaign_id": cid,
                    "campaign_name": brief.get("name", cid),
                    "replied_at": d.get("replied_at", ""),
                    "reply_preview": d.get("reply_preview", ""),
                    "reply_subject": d.get("reply_subject", ""),
                })

        send_details = progress.get("send_details", [])
        validation = {
            "valid":       sum(1 for d in send_details if d.get("validation_status") == "valid"),
            "invalid":     sum(1 for d in send_details if d.get("validation_status") == "invalid"),
            "risky":       sum(1 for d in send_details if d.get("validation_status") == "risky"),
            "unknown":     sum(1 for d in send_details if d.get("validation_status") == "unknown"),
            "unvalidated": sum(1 for d in send_details if not d.get("validation_status")),
        }
        validation["skipped"] = validation["invalid"] + validation["risky"]
        validation["checked"] = len(send_details) - validation["unvalidated"]

        failed_count  = sum(1 for d in send_details if d.get("status") == "failed")
        skipped_count = sum(1 for d in send_details if d.get("status") == "skipped")

        campaigns_info.append({
            "id": cid,
            "name": brief.get("name", cid),
            "account": brief.get("account_name", "—"),
            "status": brief.get("status", "active"),
            "campaign_status": campaign_status,
            "next_step_send_at": next_send_at,
            "next_send_label": next_send_label,
            "sent": sent,
            "total_recipients": progress.get("total_recipients", 0),
            "pending": progress.get("pending", 0),
            "failed": failed_count,
            "skipped": skipped_count,
            "undelivered": failed_count + skipped_count,
            "opens": opens_for_campaign,
            "open_rate": open_rate,
            "replied": replied_count,
            "total_steps": brief.get("total_steps", 1),
            "current_step": progress.get("current_step", 1),
            "last_open": next(
                (r["last_open"] for r in campaign_rows if r["campaign_id"] == cid), None
            ),
            "validation": validation,
        })

    existing_ids = {c["id"] for c in campaigns_info}
    total_opens = sum(r["open_count"] for r in campaign_rows if r["campaign_id"] in existing_ids)
    avg_open_rate = f"{total_opens / total_sent * 100:.1f}%" if total_sent > 0 else "—"
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
# Daily stats
# ---------------------------------------------------------------------------

def get_daily_stats():
    """Aggregate day-wise sent, opens, replies, open rate, reply rate (last 30 days).

    Open rate is computed correctly: for emails sent on day X, how many of those
    specific (recipient, campaign_id) pairs ever opened the email (on any day).
    This avoids the false inflation from same-day comparisons across different emails.
    """
    from collections import defaultdict

    # Build a set of all (campaign_id, recipient) pairs that ever opened
    all_opens_rows = query_db("SELECT DISTINCT campaign_id, recipient FROM opens")
    ever_opened = {(r["campaign_id"], r["recipient"]) for r in all_opens_rows}

    all_campaigns = query_db("SELECT campaign_id, brief, progress FROM campaigns")

    sent_by_day      = defaultdict(int)
    opened_by_day    = defaultdict(int)   # of emails sent on day X, how many opened
    replied_by_day   = defaultdict(int)
    campaigns_by_day = defaultdict(int)

    for row in all_campaigns:
        cid      = row["campaign_id"]
        brief    = row["brief"]    if isinstance(row["brief"],    dict) else json.loads(row["brief"])
        progress = row["progress"] if isinstance(row["progress"], dict) else json.loads(row["progress"])

        created_at = brief.get("created_at", "")
        if created_at:
            try:
                campaigns_by_day[created_at[:10]] += 1
            except Exception:
                pass

        for detail in progress.get("send_details", []):
            sent_at = detail.get("sent_at")
            recipient = detail.get("recipient", "")
            if sent_at and detail.get("status") == "sent":
                try:
                    day = sent_at[:10]
                    sent_by_day[day] += 1
                    if (cid, recipient) in ever_opened:
                        opened_by_day[day] += 1
                except Exception:
                    pass
            replied_at = detail.get("replied_at")
            if replied_at and detail.get("replied"):
                try:
                    replied_by_day[replied_at[:10]] += 1
                except Exception:
                    pass

    all_days = set(sent_by_day) | set(replied_by_day) | set(campaigns_by_day)

    daily = []
    for day in sorted(all_days, reverse=True)[:30]:
        sent    = sent_by_day.get(day, 0)
        opened  = opened_by_day.get(day, 0)
        replies = replied_by_day.get(day, 0)
        daily.append({
            "day":        day,
            "campaigns":  campaigns_by_day.get(day, 0),
            "sent":       sent,
            "opens":      opened,
            "replies":    replies,
            "open_rate":  f"{opened / sent * 100:.1f}%" if sent > 0 else "—",
            "reply_rate": f"{replies / sent * 100:.1f}%" if sent > 0 else "—",
        })
    return daily


def get_campaign_performance():
    """Per-campaign stats table for the dashboard reporting section."""
    all_campaigns = query_db("""
        SELECT campaign_id, brief, progress FROM campaigns ORDER BY created_at DESC
    """)
    opens_rows = query_db("""
        SELECT campaign_id, COUNT(DISTINCT recipient) as opens FROM opens GROUP BY campaign_id
    """)
    opens_map = {r["campaign_id"]: r["opens"] for r in opens_rows}

    rows = []
    for row in all_campaigns:
        brief    = row["brief"]    if isinstance(row["brief"],    dict) else json.loads(row["brief"])
        progress = row["progress"] if isinstance(row["progress"], dict) else json.loads(row["progress"])
        cid = row["campaign_id"]

        sent    = progress.get("sent", 0)
        opens   = opens_map.get(cid, 0)
        replies = sum(1 for d in progress.get("send_details", []) if d.get("replied"))
        total   = progress.get("total_recipients", 0)

        rows.append({
            "id":           cid,
            "name":         brief.get("name", cid),
            "account":      brief.get("account_name", "—"),
            "date":         brief.get("created_at", "")[:10],
            "total":        total,
            "sent":         sent,
            "opens":        opens,
            "replies":      replies,
            "open_rate":    f"{opens / sent * 100:.1f}%" if sent > 0 else "—",
            "reply_rate":   f"{replies / sent * 100:.1f}%" if sent > 0 else "—",
            "status":       progress.get("campaign_status", "active"),
        })
    return rows


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    stats = get_dashboard_stats()
    stats["daily_stats"] = get_daily_stats()
    stats["campaign_performance"] = get_campaign_performance()
    return render_template("dashboard.html", **stats)


def get_tracker_url():
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
                delay_days = max(0, int(request.form.get(f"delay_days_{step_num}", "2") or "0"))
            except (ValueError, TypeError):
                delay_days = 2
            try:
                delay_minutes = max(0, int(request.form.get(f"delay_minutes_{step_num}", "0") or "0"))
            except (ValueError, TypeError):
                delay_minutes = 0
            sequences.append({
                "step": step_num,
                "delay_days": delay_days,
                "delay_minutes": delay_minutes,
                "subject": subj or subject_1,
                "body": bod or body_1,
            })

    if not campaign_id:
        campaign_id = f"camp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Save uploaded attachments per step
    for step_num in [1, 2, 3]:
        files = request.files.getlist(f"attachments_{step_num}")
        for f in files:
            if f and f.filename:
                import base64
                raw = f.read()
                if not raw:
                    continue
                b64 = base64.b64encode(raw).decode("utf-8")
                ctype = f.content_type or "application/octet-stream"
                try:
                    save_attachment(campaign_id, step_num, f.filename, ctype, b64)
                except Exception as e:
                    print(f"[ATTACH] Warning: could not save {f.filename}: {e}")

    n_steps = len(sequences)
    campaign_label = request.form.get("campaign_name", "").strip() or sequences[0]["subject"]

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
# Tracking routes
# ---------------------------------------------------------------------------

INTERNAL_DOMAINS = {"kenresearch.com"}

@app.route("/track/pixel", methods=["GET"])
def track_pixel():
    campaign_id = request.args.get("campaign_id", "unknown")
    recipient = request.args.get("recipient", "unknown")
    step = request.args.get("step", "0")
    user_agent = request.headers.get("User-Agent", "")
    ip_address = request.remote_addr
    timestamp = datetime.utcnow().isoformat()

    # Skip tracking for internal team emails
    domain = recipient.split("@")[-1].lower() if "@" in recipient else ""
    if domain not in INTERNAL_DOMAINS:
        execute_db(
            """INSERT INTO opens (campaign_id, recipient, step, timestamp, user_agent, ip_address)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (campaign_id, recipient, int(step), timestamp, user_agent, ip_address),
        )
    return send_file(BytesIO(PIXEL), mimetype="image/png")


@app.route("/api/opens", methods=["GET"])
def get_opens():
    campaign_id = request.args.get("campaign_id", "")
    since = request.args.get("since", "2000-01-01T00:00:00")

    if campaign_id:
        rows = query_db(
            """SELECT campaign_id, recipient, step, timestamp, user_agent, ip_address
               FROM opens WHERE campaign_id = %s AND timestamp > %s
               ORDER BY timestamp DESC""",
            (campaign_id, since),
        )
    else:
        rows = query_db(
            """SELECT campaign_id, recipient, step, timestamp, user_agent, ip_address
               FROM opens WHERE timestamp > %s
               ORDER BY timestamp DESC""",
            (since,),
        )

    return jsonify({"opens": [dict(r) for r in rows], "count": len(rows)})


@app.route("/api/metrics/<campaign_id>", methods=["GET"])
def api_metrics(campaign_id):
    brief = _load_brief(campaign_id)
    progress = _load_progress(campaign_id)
    opens_row = query_db(
        "SELECT COUNT(DISTINCT recipient) as cnt, MAX(timestamp) as last_open FROM opens WHERE campaign_id = %s",
        (campaign_id,), one=True,
    )
    open_count = opens_row["cnt"] if opens_row else 0
    total_sent = progress.get("total_recipients", 0)
    open_rate = f"{open_count / total_sent * 100:.1f}%" if total_sent > 0 else "0%"
    return jsonify({
        "campaign_id": campaign_id,
        "campaign_name": brief.get("name", "Unknown"),
        "account": brief.get("account_name", "Unknown"),
        "created_at": brief.get("created_at", "N/A"),
        "total_sent": total_sent,
        "opens": open_count,
        "open_rate": open_rate,
        "last_open": opens_row["last_open"] if opens_row else None,
        "pending": progress.get("pending", 0),
        "failed": progress.get("failed", 0),
    })


@app.route("/delete/<campaign_id>", methods=["POST"])
def delete_campaign(campaign_id):
    try:
        execute_db("DELETE FROM opens WHERE campaign_id = %s", (campaign_id,))
        execute_db("DELETE FROM attachments WHERE campaign_id = %s", (campaign_id,))
        execute_db("DELETE FROM campaigns WHERE campaign_id = %s", (campaign_id,))
        flash(f"Campaign {campaign_id} deleted.", "success")
    except Exception as e:
        flash(f"Error deleting campaign: {str(e)}", "error")
    return redirect(url_for("dashboard"))


@app.route("/resume/<campaign_id>", methods=["POST"])
def resume_campaign(campaign_id):
    try:
        progress = _load_progress(campaign_id)
        brief = _load_brief(campaign_id)

        if not progress or not brief:
            flash(f"Campaign '{campaign_id}' not found.", "error")
            return redirect(url_for("dashboard"))

        campaign_status = progress.get("campaign_status", "active")
        if campaign_status == "completed":
            flash("Campaign already completed -- all steps sent.", "error")
            return redirect(url_for("dashboard"))

        current_step = progress.get("current_step", 1)
        all_sequences = brief.get("email_sequences", [])

        pending_recipients = [
            {"email": d["recipient"], "first_name": d.get("first_name", ""), "company": d.get("company", "")}
            for d in progress.get("send_details", [])
            if current_step not in d.get("steps_completed", [])
            and d.get("status") not in ("failed", "skipped")
            and not d.get("replied")
        ]
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

        remaining = [s for s in all_sequences if s["step"] >= current_step] or all_sequences
        remaining = [dict(remaining[0], delay_days=0)] + remaining[1:]

        progress["campaign_status"] = "active"
        progress["next_step_send_at"] = None
        progress["last_update"] = datetime.now().isoformat()
        _save_progress(campaign_id, progress)

        threading.Thread(
            target=bulk_send_worker,
            args=(campaign_id, account_num, pending_recipients, remaining, tracker_url),
            daemon=True,
        ).start()

        if campaign_status == "waiting":
            flash(f"'{campaign_id}': Step {current_step} sending now "
                  f"({len(pending_recipients)} recipients) -- scheduled wait overridden.", "success")
        else:
            flash(f"'{campaign_id}': Resumed Step {current_step} "
                  f"({len(pending_recipients)} pending recipients).", "success")

    except Exception as e:
        flash(f"Error resuming: {str(e)}", "error")
    return redirect(url_for("dashboard"))


@app.route("/campaign/<campaign_id>")
def campaign_detail(campaign_id):
    brief = _load_brief(campaign_id)
    progress = _load_progress(campaign_id)
    if not brief:
        flash(f"Campaign '{campaign_id}' not found.", "error")
        return redirect(url_for("dashboard"))
    return render_template(
        "campaign_detail.html",
        brief=brief,
        progress=progress,
        campaign_id=campaign_id,
        recipients=progress.get("send_details", []),
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/debug/reply/<campaign_id>", methods=["GET"])
def debug_reply(campaign_id):
    """Debug endpoint: calls Graph API directly and returns full raw response."""
    import requests as req
    import base64
    from send_email import get_access_token, ACCOUNTS, TENANT_ID

    def decode_token(token):
        try:
            payload = token.split('.')[1]
            payload += '=' * (4 - len(payload) % 4)
            return json.loads(base64.urlsafe_b64decode(payload))
        except Exception as e:
            return {"decode_error": str(e)}

    try:
        brief = _load_brief(campaign_id)
        progress = _load_progress(campaign_id)

        if not brief:
            return jsonify({"error": f"Campaign '{campaign_id}' not found"}), 404

        account_num = brief.get("account_number", "1")
        account = ACCOUNTS[account_num]
        created_at = brief.get("created_at", "")
        recipients_in_campaign = [d["recipient"] for d in progress.get("send_details", [])]

        # Step 1: get token
        token = get_access_token(account["client_id"], account["client_secret"])
        if not token:
            return jsonify({"error": "Failed to get access token — check client_id/secret"}), 500

        # Decode token to inspect granted roles
        token_claims = decode_token(token)
        token_roles = token_claims.get("roles", [])

        # Step 2: call Graph API directly and return full response
        since_str = datetime.fromisoformat(created_at).strftime("%Y-%m-%dT%H:%M:%SZ") if created_at else None
        params = {
            "$select": "from,subject,receivedDateTime,bodyPreview",
            "$top": "20",
            "$orderby": "receivedDateTime desc",
        }
        if since_str:
            params["$filter"] = f"receivedDateTime ge {since_str}"

        resp = req.get(
            f"https://graph.microsoft.com/v1.0/users/{account['email']}/mailFolders/Inbox/messages",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )

        return jsonify({
            "campaign_id": campaign_id,
            "account_num": account_num,
            "sender_email": account["email"],
            "since_filter": since_str,
            "recipients_in_campaign": recipients_in_campaign,
            "token_roles": token_roles,
            "mail_read_in_token": "Mail.Read" in token_roles,
            "graph_api_status": resp.status_code,
            "graph_api_response": resp.json(),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------

@app.template_filter("friendly_dt")
def friendly_dt(value):
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", ""))
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        return value


# ---------------------------------------------------------------------------
# Startup workers
# ---------------------------------------------------------------------------

def auto_resume_pending_campaigns():
    """On startup, resume active/waiting campaigns from Supabase state."""
    try:
        all_campaigns = query_db("SELECT campaign_id, brief, progress FROM campaigns")
    except Exception as e:
        print(f"[AUTO-RESUME] DB query failed: {e}")
        return

    resumed = 0
    for row in all_campaigns:
        try:
            brief = row["brief"] if isinstance(row["brief"], dict) else json.loads(row["brief"])
            progress = row["progress"] if isinstance(row["progress"], dict) else json.loads(row["progress"])
            campaign_id = row["campaign_id"]

            campaign_status = progress.get("campaign_status", "active")
            if campaign_status == "completed":
                continue

            current_step = progress.get("current_step", 1)
            all_sequences = brief.get("email_sequences", [])

            pending = [
                {"email": d["recipient"], "first_name": d.get("first_name", ""), "company": d.get("company", "")}
                for d in progress.get("send_details", [])
                if current_step not in d.get("steps_completed", [])
                and d.get("status") not in ("failed", "skipped")
                and not d.get("replied")
            ]
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
            remaining_seqs = [s for s in all_sequences if s["step"] >= current_step] or all_sequences

            if campaign_status == "waiting":
                try:
                    label = datetime.fromisoformat(progress.get("next_step_send_at", "")).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    label = "scheduled time"
                print(f"[AUTO-RESUME] {campaign_id}: Step {current_step} waiting until {label}, {len(pending)} recipients.")
            else:
                remaining_seqs = [dict(remaining_seqs[0], delay_days=0)] + remaining_seqs[1:]
                print(f"[AUTO-RESUME] {campaign_id}: Step {current_step} active, resuming {len(pending)} recipients.")

            threading.Thread(
                target=bulk_send_worker,
                args=(campaign_id, account_num, pending, remaining_seqs, tracker_url),
                daemon=True,
            ).start()
            resumed += 1

        except Exception as e:
            print(f"[AUTO-RESUME ERROR] {row.get('campaign_id', '?')}: {e}")

    if resumed:
        print(f"[OK] Auto-resumed {resumed} campaign(s)")


def reply_checker_worker():
    """Background thread: polls sender inboxes every 60s for replies."""
    import time
    from send_email import read_inbox

    while True:
        time.sleep(60)
        try:
            all_campaigns = query_db("SELECT campaign_id, brief, progress FROM campaigns")
        except Exception:
            continue

        for row in all_campaigns:
            try:
                brief = row["brief"] if isinstance(row["brief"], dict) else json.loads(row["brief"])
                progress = row["progress"] if isinstance(row["progress"], dict) else json.loads(row["progress"])
                campaign_id = row["campaign_id"]

                account_num = brief.get("account_number", "1")
                try:
                    since_dt = datetime.fromisoformat(brief.get("created_at", ""))
                except Exception:
                    since_dt = None

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
                            print(f"[REPLY] {campaign_id}: reply from {from_email} at {msg['received_at']}")
                            break

                if updated:
                    progress["last_update"] = datetime.now().isoformat()
                    _save_progress(campaign_id, progress)

            except Exception as e:
                print(f"[REPLY CHECK ERROR] {row.get('campaign_id', '?')}: {e}")


# Run on startup regardless of whether launched via Python or gunicorn
init_db()
auto_resume_pending_campaigns()
threading.Thread(target=reply_checker_worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    print(f"[OK] Ken Research Email Campaign App running on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
