#!/usr/bin/env python3
"""
Scheduler - Rate-limited email sender with threading and retry logic
Sends emails at 4-5 minute random intervals
"""

import os
import sys
import json
import csv
import time
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from send_email import send_email
from email_validator import validate_email
from campaign_manager import CAMPAIGNS_DIR, DB_PATH, load_campaign, save_progress

def get_pending_recipients(progress):
    """Get list of recipients still pending"""
    pending = []
    for detail in progress.get("send_details", []):
        if detail.get("status") == "pending" or detail.get("status") == "failed":
            if detail.get("retry_count", 0) < 2:  # Max 2 retries
                pending.append(detail)
    return pending

def get_recipients_needing_step(campaign_data, step):
    """Get recipients who need this step email sent"""
    progress = campaign_data["progress"]
    brief = campaign_data["brief"]

    # Find sequence for this step
    sequence = next((s for s in brief["email_sequences"] if s["step"] == step), None)
    if not sequence:
        return []

    recipients_needing_step = []

    for detail in progress.get("send_details", []):
        # If they haven't received this step yet and previous step was sent
        if detail.get("step") < step:
            # Check if enough days have passed
            sent_at = datetime.fromisoformat(detail.get("sent_at", "2000-01-01"))
            delay_days = sequence["delay_days"]
            ready_at = sent_at + timedelta(days=delay_days)

            if datetime.now() >= ready_at:
                recipients_needing_step.append(detail)

    return recipients_needing_step

def load_recipients(campaign_folder):
    """Load recipients from CSV"""
    recipients_path = campaign_folder / "recipients.csv"

    if not recipients_path.exists():
        return []

    recipients = []
    with open(recipients_path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            recipients.append(row["email"])

    return recipients

def initialize_send_details(progress, recipients):
    """Initialize send_details for all recipients if not exists"""
    existing_emails = {d["recipient"] for d in progress.get("send_details", [])}

    for recipient in recipients:
        if recipient not in existing_emails:
            progress["send_details"].append({
                "recipient": recipient,
                "step": 0,
                "status": "pending",
                "message_id": None,
                "sent_at": None,
                "retry_count": 0
            })

    return progress

def run_scheduler(campaign_id, test_mode=False):
    """Main scheduler loop for a campaign"""
    campaign_data = load_campaign(campaign_id)

    if not campaign_data:
        print(f"[ERROR] Cannot load campaign: {campaign_id}")
        return

    brief = campaign_data["brief"]
    progress = campaign_data["progress"]
    account_num = brief["account_number"]
    sequences = brief["email_sequences"]

    # Test mode: faster delays (5 seconds instead of 4-5 minutes)
    if test_mode:
        min_delay = 1
        max_delay = 5
    else:
        min_delay = 240  # 4 minutes
        max_delay = 300  # 5 minutes

    print(f"\n{'='*60}")
    print(f"SCHEDULER: {brief['name']}")
    print(f"{'='*60}")
    print(f"Account: {brief['account_name']}")
    print(f"Recipients: {progress['total_recipients']}")
    print(f"Status: {progress['sent']} sent | {progress['pending']} pending | {progress['failed']} failed")

    # Load recipients
    recipients = load_recipients(campaign_data["folder"])
    progress = initialize_send_details(progress, recipients)

    # Process all steps
    for step in range(1, len(sequences) + 1):
        sequence = sequences[step - 1]
        print(f"\n[STEP {step}] {sequence['subject']}")

        for detail in progress.get("send_details", []):
            recipient = detail["recipient"]

            # Skip if already sent this step
            if detail.get("status") == "sent" and detail.get("step") >= step:
                continue

            # Only send if ready for this step
            if detail.get("step") >= step:
                continue

            # Check if previous step was sent
            if step > 1 and detail.get("step") < step - 1:
                continue

            # Check if enough time has passed
            if step > 1:
                sent_at = datetime.fromisoformat(detail.get("sent_at", "2000-01-01"))
                delay_days = sequence.get("delay_days", 0)
                delay_minutes = sequence.get("delay_minutes", 0)
                ready_at = sent_at + timedelta(days=delay_days, minutes=delay_minutes)
                if datetime.now() < ready_at:
                    continue

            # Skip if failed too many times
            if detail.get("retry_count", 0) >= 2:
                if detail.get("status") != "failed":
                    print(f"  SKIP {recipient} (max retries reached)")
                    detail["status"] = "failed"
                continue

            # Random delay (configurable for testing)
            delay = random.uniform(min_delay, max_delay)
            print(f"  WAIT {int(delay)}s before sending to {recipient}...")
            time.sleep(delay)

            # Validate email before sending
            validation = validate_email(recipient)

            if not validation["valid"]:
                # Email is invalid - skip
                detail["status"] = "skipped"
                detail["validation_status"] = validation["status"]
                progress["failed"] += 1
                progress["pending"] -= 1
                print(f"    [SKIP] {recipient} - {validation['message']}")

                # Log to file
                log_path = campaign_data["folder"] / "send_log.txt"
                with open(log_path, "a") as f:
                    f.write(f"[SKIP] Step {step} -> {recipient} at {datetime.now()} (Reason: {validation['message']})\n")

                # Save progress
                progress["last_update"] = datetime.now().isoformat()
                save_progress(campaign_id, progress)
                continue

            # Email is valid - proceed with sending
            # Determine if threading needed
            in_reply_to = detail.get("message_id") if step > 1 else None

            # Send email
            result = send_email(
                account_num,
                recipient,
                subject=sequence["subject"],
                body=sequence["body"],
                in_reply_to=in_reply_to
            )

            # Update progress
            if result is True:
                detail["status"] = "sent"
                detail["step"] = step
                detail["sent_at"] = datetime.now().isoformat()
                detail["retry_count"] = 0
                detail["validation_status"] = "valid"
                progress["sent"] += 1
                progress["pending"] -= 1
                print(f"    [SENT] {recipient}")

                # Log to file
                log_path = campaign_data["folder"] / "send_log.txt"
                with open(log_path, "a") as f:
                    f.write(f"[SENT] Step {step} -> {recipient} at {datetime.now()} (Validated: {validation['status']})\n")

                # Save progress immediately after each successful send
                progress["last_update"] = datetime.now().isoformat()
                save_progress(campaign_id, progress)

            elif result is None:
                # Failed, increment retry count
                detail["retry_count"] = detail.get("retry_count", 0) + 1
                if detail["retry_count"] >= 2:
                    detail["status"] = "failed"
                    progress["failed"] += 1
                    progress["pending"] -= 1
                    print(f"    [FAILED] Max retries: {recipient}")
                else:
                    detail["status"] = "pending"
                    print(f"    [RETRY] {detail['retry_count']}/2: {recipient}")

                # Log to file
                log_path = campaign_data["folder"] / "send_log.txt"
                with open(log_path, "a") as f:
                    f.write(f"[FAILED] Step {step} -> {recipient} at {datetime.now()} (retry {detail['retry_count']}/2)\n")

                # Save progress immediately after each send (success or fail)
                progress["last_update"] = datetime.now().isoformat()
                save_progress(campaign_id, progress)

        # Final progress update at end of step
        progress["current_step"] = step
        save_progress(campaign_id, progress)

    print(f"\n[DONE] Campaign complete")
    print(f"  Sent: {progress['sent']}")
    print(f"  Failed: {progress['failed']}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scheduler.py <campaign_id> [--test]")
        print("  --test  : Fast mode (1-5s delays instead of 4-5min)")
        sys.exit(1)

    campaign_id = sys.argv[1]
    test_mode = "--test" in sys.argv
    run_scheduler(campaign_id, test_mode=test_mode)
