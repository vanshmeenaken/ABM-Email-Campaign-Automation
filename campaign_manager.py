#!/usr/bin/env python3
"""
Campaign Manager - Create, manage, and persist campaigns
Stores campaign briefs, recipient lists, and progress tracking
"""

import os
import json
import csv
import sqlite3
import requests
from datetime import datetime
from pathlib import Path

CAMPAIGNS_DIR = Path(__file__).parent / "campaigns"
DB_PATH = Path(__file__).parent / "campaigns.db"

ACCOUNTS = {
    "1": "Alina Khan (ABM)",
    "2": "Archita Singh (ABM)",
    "3": "Sneha Malhotra (ABM)",
    "4": "Tanushree Kalita (ABM)",
    "5": "Shreya Gupta (Outlook)",
    "6": "Ken Research Updates",
}

def init_database():
    """Initialize SQLite database for campaign tracking"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        account TEXT NOT NULL,
        created_at TEXT,
        status TEXT DEFAULT 'active',
        total_recipients INTEGER,
        sent INTEGER DEFAULT 0,
        pending INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS campaign_sends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT,
        recipient TEXT,
        step INTEGER,
        status TEXT,
        message_id TEXT,
        sent_at TEXT,
        retry_count INTEGER DEFAULT 0,
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
    )''')

    conn.commit()
    conn.close()

def get_email_opens(campaign_id, tracker_url="http://localhost:5000"):
    """Query email opens from tracker server"""
    try:
        response = requests.get(
            f"{tracker_url}/api/opens",
            params={"campaign_id": campaign_id},
            timeout=5
        )
        if response.status_code == 200:
            return response.json().get("opens", [])
        else:
            print(f"[WARNING] Tracker returned {response.status_code}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"[WARNING] Could not reach tracker: {str(e)}")
        return []

def update_campaign_opens(campaign_id, tracker_url="http://localhost:5000"):
    """Fetch opens from tracker and update campaign progress"""
    opens = get_email_opens(campaign_id, tracker_url)

    if not opens:
        print(f"[INFO] No opens found for campaign {campaign_id}")
        return

    campaign_data = load_campaign(campaign_id)
    if not campaign_data:
        return

    progress = campaign_data["progress"]
    opened_recipients = set(op["recipient"] for op in opens)

    progress["opens"] = len(opened_recipients)
    progress["open_rate"] = f"{(len(opened_recipients) / progress['total_recipients'] * 100):.1f}%" if progress['total_recipients'] > 0 else "0%"
    progress["last_opens_update"] = datetime.now().isoformat()
    progress["open_details"] = opens

    save_progress(campaign_id, progress)
    print(f"[OK] Updated opens: {len(opened_recipients)} opened ({progress['open_rate']})")

def create_campaign():
    """Interactive campaign creation"""
    print("\n" + "="*60)
    print("CREATE NEW CAMPAIGN")
    print("="*60)

    # Campaign name
    campaign_name = input("\nCampaign name? ").strip()
    if not campaign_name:
        print("[ERROR] Campaign name required")
        return None

    # Account selection
    print("\nSelect account:")
    for num, name in ACCOUNTS.items():
        print(f"  {num} = {name}")
    account_num = input("Account (1-6)? ").strip()
    if account_num not in ACCOUNTS:
        print("[ERROR] Invalid account")
        return None

    # Recipients list
    print("\nPaste recipient list (one email per line, or email,name format):")
    print("(Press ENTER twice when done)")
    recipients = []
    while True:
        line = input().strip()
        if not line:
            if recipients:
                break
            continue
        recipients.append(line.split(',')[0].strip())

    if not recipients:
        print("[ERROR] No recipients provided")
        return None

    # Email sequences
    sequences = []
    step = 1
    while True:
        print(f"\nEmail Sequence Step {step}:")
        subject = input("  Subject? ").strip()
        if not subject:
            if step == 1:
                print("[ERROR] At least 1 email sequence required")
                continue
            break

        print("  Body (paste, press ENTER twice when done):")
        body_lines = []
        while True:
            line = input().strip()
            if not line:
                if body_lines:
                    break
                continue
            body_lines.append(line)
        body = "\n".join(body_lines)

        delay_days = input("  Delay (days from step 1)? [0] ").strip() or "0"
        try:
            delay_days = int(delay_days)
        except ValueError:
            delay_days = 0

        sequences.append({
            "step": step,
            "delay_days": delay_days,
            "subject": subject,
            "body": body
        })
        step += 1

        more = input("\nAdd another sequence? (y/n) [n] ").strip().lower()
        if more != 'y':
            break

    # Create campaign folder
    campaign_id = f"campaign_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    campaign_folder = CAMPAIGNS_DIR / campaign_id
    campaign_folder.mkdir(parents=True, exist_ok=True)

    # Save campaign brief
    brief = {
        "campaign_id": campaign_id,
        "name": campaign_name,
        "account_number": account_num,
        "account_name": ACCOUNTS[account_num],
        "created_at": datetime.now().isoformat(),
        "status": "active",
        "total_recipients": len(recipients),
        "email_sequences": sequences
    }

    with open(campaign_folder / "brief.json", "w") as f:
        json.dump(brief, f, indent=2)

    # Save recipients list
    with open(campaign_folder / "recipients.csv", "w", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["email"])
        for recipient in recipients:
            writer.writerow([recipient])

    # Initialize progress
    progress = {
        "campaign_id": campaign_id,
        "total_recipients": len(recipients),
        "sent": 0,
        "pending": len(recipients),
        "failed": 0,
        "retry_queue": 0,
        "last_update": datetime.now().isoformat(),
        "current_step": 1,
        "send_details": []
    }

    with open(campaign_folder / "progress.json", "w") as f:
        json.dump(progress, f, indent=2)

    # Log file
    with open(campaign_folder / "send_log.txt", "w") as f:
        f.write(f"Campaign: {campaign_name}\n")
        f.write(f"Account: {ACCOUNTS[account_num]}\n")
        f.write(f"Recipients: {len(recipients)}\n")
        f.write(f"Created: {datetime.now()}\n")
        f.write("="*60 + "\n\n")

    # Save to database
    init_database()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO campaigns (id, name, account, created_at, total_recipients, pending)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (campaign_id, campaign_name, account_num, datetime.now().isoformat(), len(recipients), len(recipients)))
    conn.commit()
    conn.close()

    print(f"\n[CREATED] Campaign: {campaign_id}")
    print(f"    Location: {campaign_folder}")
    print(f"    Recipients: {len(recipients)}")
    print(f"    Sequences: {len(sequences)}")
    return campaign_id

def list_campaigns():
    """List all campaigns with status"""
    if not CAMPAIGNS_DIR.exists():
        print("[INFO] No campaigns yet")
        return

    print("\n" + "="*60)
    print("CAMPAIGNS")
    print("="*60)

    campaigns = sorted([d for d in CAMPAIGNS_DIR.iterdir() if d.is_dir()])

    if not campaigns:
        print("[INFO] No campaigns found")
        return

    for campaign_folder in campaigns:
        brief_path = campaign_folder / "brief.json"
        progress_path = campaign_folder / "progress.json"

        if brief_path.exists() and progress_path.exists():
            with open(brief_path) as f:
                brief = json.load(f)
            with open(progress_path) as f:
                progress = json.load(f)

            print(f"\n{campaign_folder.name}")
            print(f"  Campaign: {brief['name']}")
            print(f"  Account: {brief['account_name']}")
            print(f"  Status: {brief['status']}")
            print(f"  Progress: {progress['sent']}/{progress['total_recipients']} sent")
            print(f"  Pending: {progress['pending']} | Failed: {progress['failed']}")

def load_campaign(campaign_id):
    """Load campaign by ID"""
    campaign_folder = CAMPAIGNS_DIR / campaign_id

    if not campaign_folder.exists():
        print(f"[ERROR] Campaign not found: {campaign_id}")
        return None

    brief_path = campaign_folder / "brief.json"
    progress_path = campaign_folder / "progress.json"

    if not (brief_path.exists() and progress_path.exists()):
        print(f"[ERROR] Campaign data missing: {campaign_id}")
        return None

    with open(brief_path) as f:
        brief = json.load(f)
    with open(progress_path) as f:
        progress = json.load(f)

    return {
        "folder": campaign_folder,
        "brief": brief,
        "progress": progress
    }

def save_progress(campaign_id, progress):
    """Save progress back to file"""
    campaign_folder = CAMPAIGNS_DIR / campaign_id
    progress_path = campaign_folder / "progress.json"

    with open(progress_path, "w") as f:
        json.dump(progress, f, indent=2)

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "create":
            create_campaign()
        elif sys.argv[1] == "list":
            list_campaigns()
        elif sys.argv[1] == "opens":
            if len(sys.argv) < 3:
                print("[ERROR] Usage: python campaign_manager.py opens <campaign_id> [tracker_url]")
                sys.exit(1)
            campaign_id = sys.argv[2]
            tracker_url = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:5000"
            update_campaign_opens(campaign_id, tracker_url)
        elif sys.argv[1] == "view":
            if len(sys.argv) < 3:
                print("[ERROR] Usage: python campaign_manager.py view <campaign_id>")
                sys.exit(1)
            campaign_id = sys.argv[2]
            data = load_campaign(campaign_id)
            if data:
                print(f"\nCampaign: {data['brief']['name']}")
                print(f"Status: {data['brief']['status']}")
                print(f"Progress: {data['progress']['sent']}/{data['progress']['total_recipients']} sent")
                if "opens" in data["progress"]:
                    print(f"Opens: {data['progress']['opens']} ({data['progress']['open_rate']})")
    else:
        print("\nUsage:")
        print("  python campaign_manager.py create             - Create new campaign")
        print("  python campaign_manager.py list               - List all campaigns")
        print("  python campaign_manager.py view <campaign_id> - View campaign details")
        print("  python campaign_manager.py opens <campaign_id> [tracker_url] - Update opens from tracker")
