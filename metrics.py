#!/usr/bin/env python3
"""
Campaign Metrics CLI Wrapper
Simple interface to get campaign stats without technical jargon
Usage: python metrics.py <campaign_id> [tracker_url]
"""

import sys
import json
import requests
from pathlib import Path
from campaign_manager import load_campaign

def get_campaign_metrics(campaign_id, tracker_url="http://localhost:5000"):
    """Get clean metrics for campaign"""

    # Load campaign data if exists
    campaign_data = load_campaign(campaign_id)
    brief = campaign_data["brief"] if campaign_data else None
    progress = campaign_data["progress"] if campaign_data else None

    # Query tracker for opens
    try:
        response = requests.get(
            f"{tracker_url}/api/opens",
            params={"campaign_id": campaign_id},
            timeout=5
        )
        opens_data = response.json() if response.status_code == 200 else {"opens": [], "count": 0}
    except:
        opens_data = {"opens": [], "count": 0}

    opens = opens_data.get("opens", [])
    open_count = len(opens)

    # Calculate metrics
    total_sent = progress["total_recipients"] if progress else 0
    open_rate = (open_count / total_sent * 100) if total_sent > 0 else 0

    return {
        "campaign_id": campaign_id,
        "campaign_name": brief["name"] if brief else "Unknown",
        "created_at": brief["created_at"] if brief else "N/A",
        "account": brief["account_name"] if brief else "Unknown",
        "total_sent": total_sent,
        "opened": open_count,
        "open_rate": f"{open_rate:.1f}%",
        "pending": progress["pending"] if progress else 0,
        "failed": progress["failed"] if progress else 0,
        "opens": opens
    }

def print_metrics(metrics):
    """Print clean metrics output"""
    print("\n" + "="*70)
    print("CAMPAIGN METRICS")
    print("="*70)

    print(f"\n📧 Campaign: {metrics['campaign_name']}")
    print(f"   ID: {metrics['campaign_id']}")
    print(f"   Account: {metrics['account']}")
    print(f"   Created: {metrics['created_at']}")

    print(f"\n📊 Statistics:")
    print(f"   Total Sent: {metrics['total_sent']}")
    print(f"   Opened: {metrics['opened']}")
    print(f"   Open Rate: {metrics['open_rate']}")
    print(f"   Pending: {metrics['pending']}")
    print(f"   Failed: {metrics['failed']}")

    if metrics['opens']:
        print(f"\n📬 Recent Opens:")
        for op in metrics['opens'][:5]:  # Show last 5
            timestamp = op['timestamp'].split('T')[1][:8]  # HH:MM:SS
            print(f"   • {op['recipient']} — {timestamp}")
        if len(metrics['opens']) > 5:
            print(f"   ... and {len(metrics['opens']) - 5} more")
    else:
        print(f"\n📬 No opens yet")

    print("\n" + "="*70 + "\n")

def main():
    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  python metrics.py <campaign_id> [tracker_url]")
        print("\nExample:")
        print("  python metrics.py test_pixel_tracking")
        print("  python metrics.py my_campaign https://tracker.example.com")
        return

    campaign_id = sys.argv[1]
    tracker_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:5000"

    try:
        metrics = get_campaign_metrics(campaign_id, tracker_url)
        print_metrics(metrics)
    except Exception as e:
        print(f"\n[ERROR] {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
