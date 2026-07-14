#!/usr/bin/env python3
"""
Ken Research - Satellite Account Email Sender
Send test emails through 4 satellite accounts via Microsoft Graph API
Secrets loaded from environment variables for security
"""

import sys
import json
import requests
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Satellite Accounts Configuration
TENANT_ID = os.getenv("TENANT_ID")

ACCOUNTS = {
    "1": {
        "name": "Alina Khan (ABM)",
        "client_id": os.getenv("ACCOUNT_1_CLIENT_ID"),
        "client_secret": os.getenv("ACCOUNT_1_CLIENT_SECRET"),
        "email": os.getenv("ACCOUNT_1_EMAIL", "alina.khan@kenresearch.com")
    },
    "2": {
        "name": "Archita Singh (ABM)",
        "client_id": os.getenv("ACCOUNT_2_CLIENT_ID"),
        "client_secret": os.getenv("ACCOUNT_2_CLIENT_SECRET"),
        "email": os.getenv("ACCOUNT_2_EMAIL", "archita.singh@kenresearch.com")
    },
    "3": {
        "name": "Sneha Malhotra (ABM)",
        "client_id": os.getenv("ACCOUNT_3_CLIENT_ID"),
        "client_secret": os.getenv("ACCOUNT_3_CLIENT_SECRET"),
        "email": os.getenv("ACCOUNT_3_EMAIL", "sneha.malhotra@kenresearch.com")
    },
    "4": {
        "name": "Tanushree Kalita (ABM)",
        "client_id": os.getenv("ACCOUNT_4_CLIENT_ID"),
        "client_secret": os.getenv("ACCOUNT_4_CLIENT_SECRET"),
        "email": os.getenv("ACCOUNT_4_EMAIL", "tanushree.kalita@kenresearch.com")
    },
    "5": {
        "name": "Shreya Gupta (Outlook)",
        "client_id": os.getenv("ACCOUNT_5_CLIENT_ID"),
        "client_secret": os.getenv("ACCOUNT_5_CLIENT_SECRET"),
        "email": os.getenv("ACCOUNT_5_EMAIL", "Shreya.Gupta@kenresearch.com")
    }
}

def get_access_token(client_id, client_secret):
    """Get Azure AD access token"""
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default"
    }
    
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            return response.json()["access_token"]
        else:
            print(f"[FAILED] Failed to get token. Status: {response.status_code}")
            print(f"   Response: {response.text}")
            return None
    except Exception as e:
        print(f"[ERROR] Error getting token: {str(e)}")
        return None

def send_email(account_num, recipient_email, subject="Test Email", body="This is a test email", in_reply_to=None, campaign_id=None, step=1, tracker_url="http://localhost:5000", attachments=None):
    """Send email from specified satellite account with optional threading, tracking, and attachments.

    attachments: list of dicts with keys name, contentType, contentBytes (base64 str), isInline, contentId (optional)
    """

    if account_num not in ACCOUNTS:
        print(f"[ERROR] Invalid account number. Use 1, 2, 3, 4, or 5")
        return False, "Invalid account number"

    account = ACCOUNTS[account_num]

    print(f"\n[SEND] Sending email from: {account['name']}")
    print(f"   To: {recipient_email}")
    print(f"   Subject: {subject}")
    if in_reply_to:
        print(f"   In Reply To: {in_reply_to[:40]}...")

    # Get access token
    access_token = get_access_token(account["client_id"], account["client_secret"])
    if not access_token:
        return False, "OAuth token failed"

    # Embed tracking pixel if campaign_id provided
    email_body = body
    if campaign_id:
        tracking_pixel = f'<img src="{tracker_url}/track/pixel?campaign_id={campaign_id}&recipient={recipient_email}&step={step}" width="1" height="1" alt="" style="display:none;" />'
        email_body = f"{body}\n{tracking_pixel}"

    # Build email message
    message = {
        "subject": subject,
        "body": {
            "contentType": "HTML",
            "content": email_body,
        },
        "toRecipients": [
            {"emailAddress": {"address": recipient_email}}
        ],
    }

    # Add attachments
    if attachments:
        message["attachments"] = []
        for att in attachments:
            graph_att = {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att["name"],
                "contentType": att["contentType"],
                "contentBytes": att["contentBytes"],
            }
            if att.get("isInline"):
                graph_att["isInline"] = True
                graph_att["contentId"] = att.get("contentId", att["name"])
            message["attachments"].append(graph_att)

    email_data = {"message": message, "saveToSentItems": True}

    # Add threading if replying to previous email
    if in_reply_to:
        email_data["message"]["inReplyTo"] = in_reply_to

    # Send email via Graph API
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            f"https://graph.microsoft.com/v1.0/users/{account['email']}/sendMail",
            headers=headers,
            json=email_data
        )

        if response.status_code == 202:
            print(f"[OK] Email sent successfully!")
            return True, None
        else:
            try:
                err_body = response.json()
                err_msg = err_body.get("error", {}).get("message", response.text[:200])
            except Exception:
                err_msg = response.text[:200]
            reason = f"HTTP {response.status_code}: {err_msg}"
            print(f"[FAILED] Failed to send. {reason}")
            return False, reason

    except Exception as e:
        print(f"[ERROR] Error sending email: {str(e)}")
        return False, str(e)

def read_inbox(account_num, since_dt=None):
    """Read inbox messages for a sender account since a given datetime.

    Returns list of dicts:
      {"from_email", "received_at", "subject", "body_preview"}
    """
    if account_num not in ACCOUNTS:
        return []
    account = ACCOUNTS[account_num]
    access_token = get_access_token(account["client_id"], account["client_secret"])
    if not access_token:
        return []

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    params = {
        "$select": "from,subject,receivedDateTime,bodyPreview",
        "$top": "100",
        "$orderby": "receivedDateTime desc",
    }
    if since_dt:
        since_str = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["$filter"] = f"receivedDateTime ge {since_str}"

    try:
        resp = requests.get(
            f"https://graph.microsoft.com/v1.0/users/{account['email']}/mailFolders/Inbox/messages",
            headers=headers,
            params=params,
        )
        if resp.status_code == 200:
            return [
                {
                    "from_email": m.get("from", {}).get("emailAddress", {}).get("address", "").lower(),
                    "received_at": m.get("receivedDateTime", ""),
                    "subject": m.get("subject", ""),
                    "body_preview": m.get("bodyPreview", "")[:200],
                }
                for m in resp.json().get("value", [])
            ]
        else:
            print(f"[INBOX] Account {account_num} read failed: {resp.status_code} {resp.text[:200]}")
            return []
    except Exception as e:
        print(f"[INBOX ERROR] Account {account_num}: {e}")
        return []


def read_bounces(account_num, since_dt=None):
    """Read NDR / bounce notifications (Mail Delivery System, MAILER-DAEMON, postmaster)
    from a sender account's inbox since a given datetime.

    Graph API only tells us a send was ACCEPTED for relay (status 202) — it does not
    wait for the receiving server to confirm delivery. A hard bounce (bad mailbox,
    domain rejects, etc.) comes back later as a separate NDR email in the same inbox.
    This reads those NDRs with full body text so the caller can match the original
    bounced recipient address against its own campaign data.

    Returns list of dicts: {"subject", "received_at", "body_text"}
    """
    if account_num not in ACCOUNTS:
        return []
    account = ACCOUNTS[account_num]
    access_token = get_access_token(account["client_id"], account["client_secret"])
    if not access_token:
        return []

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Prefer": 'outlook.body-content-type="text"',
    }
    params = {
        "$select": "from,subject,receivedDateTime,body",
        "$top": "50",
        "$orderby": "receivedDateTime desc",
    }
    if since_dt:
        since_str = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["$filter"] = f"receivedDateTime ge {since_str}"

    try:
        resp = requests.get(
            f"https://graph.microsoft.com/v1.0/users/{account['email']}/mailFolders/Inbox/messages",
            headers=headers,
            params=params,
        )
        if resp.status_code != 200:
            print(f"[BOUNCE] Account {account_num} read failed: {resp.status_code} {resp.text[:200]}")
            return []

        bounces = []
        for m in resp.json().get("value", []):
            sender = m.get("from", {}).get("emailAddress", {}).get("address", "").lower()
            subject = m.get("subject", "") or ""
            subj_l = subject.lower()
            is_ndr = (
                "mailer-daemon" in sender
                or "postmaster" in sender
                or subj_l.startswith("undeliverable")
                or subj_l.startswith("undelivered")
                or "delivery status notification" in subj_l
                or "delivery has failed" in subj_l
                or "mail delivery failed" in subj_l
                or "delivery failure" in subj_l
            )
            if not is_ndr:
                continue
            bounces.append({
                "subject": subject,
                "received_at": m.get("receivedDateTime", ""),
                "body_text": (m.get("body", {}) or {}).get("content", "") or "",
            })
        return bounces
    except Exception as e:
        print(f"[BOUNCE ERROR] Account {account_num}: {e}")
        return []


def main():
    """Command line interface"""
    
    if len(sys.argv) < 2:
        print("\n" + "="*60)
        print("Ken Research - Satellite Account Email Sender")
        print("="*60)
        print("\nUsage:")
        print("  python send_email.py --account=<1-5> --to=<email>")
        print("\nOptions:")
        print("  --account=<1-5>        Satellite account (1=Alina, 2=Archita, 3=Sneha, 4=Tanushree, 5=Shreya)")
        print("  --to=<email>           Recipient email address (required)")
        print("  --subject=<text>       Email subject (optional)")
        print("  --body=<text>          Email body (optional)")
        print("  --campaign=<id>        Campaign ID for tracking (optional)")
        print("  --step=<n>             Email step number (optional, default=1)")
        print("  --tracker-url=<url>    Tracker server URL (optional, default=http://localhost:5000)")
        print("\nExamples:")
        print("  python send_email.py --account=1 --to=your.email@kenresearch.com")
        print("  python send_email.py --account=2 --to=team@kenresearch.com --campaign=camp_123 --step=1")
        print("="*60 + "\n")
        return
    
    # Parse arguments
    account_num = None
    recipient = None
    subject = "Test Email - Ken Research Automation"
    body = f"<p>This is a test email sent via Ken Automation satellite account.</p><p>Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"
    campaign_id = None
    step = 1
    tracker_url = "http://localhost:5000"

    for arg in sys.argv[1:]:
        if arg.startswith("--account="):
            account_num = arg.split("=", 1)[1]
        elif arg.startswith("--to="):
            recipient = arg.split("=", 1)[1]
        elif arg.startswith("--subject="):
            subject = arg.split("=", 1)[1]
        elif arg.startswith("--body="):
            body = arg.split("=", 1)[1]
        elif arg.startswith("--campaign="):
            campaign_id = arg.split("=", 1)[1]
        elif arg.startswith("--step="):
            step = int(arg.split("=", 1)[1])
        elif arg.startswith("--tracker-url="):
            tracker_url = arg.split("=", 1)[1]

    if not account_num or not recipient:
        print("[ERROR] Missing required arguments!")
        print("   Use: --account=<1-5> and --to=<email>")
        return

    send_email(account_num, recipient, subject, body, campaign_id=campaign_id, step=step, tracker_url=tracker_url)

if __name__ == "__main__":
    main()
