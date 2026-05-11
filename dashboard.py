#!/usr/bin/env python3
"""
Dashboard - Flask web interface for monitoring campaigns
Real-time progress tracking, send history, retry queue
"""

import json
import sys
from pathlib import Path
from datetime import datetime

try:
    from flask import Flask, jsonify, render_template_string
except ImportError:
    print("[ERROR] Flask not installed. Install with: pip install flask")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from campaign_manager import CAMPAIGNS_DIR, ACCOUNTS

app = Flask(__name__)

def get_all_campaigns():
    """Get all campaigns with status"""
    campaigns = []

    if not CAMPAIGNS_DIR.exists():
        return campaigns

    for campaign_folder in sorted(CAMPAIGNS_DIR.iterdir()):
        if not campaign_folder.is_dir():
            continue

        brief_path = campaign_folder / "brief.json"
        progress_path = campaign_folder / "progress.json"

        if brief_path.exists() and progress_path.exists():
            with open(brief_path) as f:
                brief = json.load(f)
            with open(progress_path) as f:
                progress = json.load(f)

            campaigns.append({
                "id": campaign_folder.name,
                "brief": brief,
                "progress": progress
            })

    return campaigns

@app.route('/')
def index():
    """Dashboard homepage"""
    campaigns = get_all_campaigns()

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ken Research - Campaign Dashboard</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: #f5f5f5;
                padding: 20px;
            }
            .container { max-width: 1200px; margin: 0 auto; }
            h1 { color: #333; margin-bottom: 10px; }
            .header {
                background: white;
                padding: 20px;
                border-radius: 8px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .campaigns-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(500px, 1fr));
                gap: 20px;
            }
            .campaign-card {
                background: white;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                transition: transform 0.2s;
            }
            .campaign-card:hover { transform: translateY(-2px); }
            .campaign-title { font-size: 18px; font-weight: bold; color: #333; margin-bottom: 10px; }
            .campaign-meta { font-size: 13px; color: #666; margin-bottom: 15px; }
            .progress-bar {
                width: 100%;
                height: 24px;
                background: #e0e0e0;
                border-radius: 4px;
                overflow: hidden;
                margin-bottom: 10px;
            }
            .progress-fill {
                height: 100%;
                background: linear-gradient(90deg, #4CAF50, #45a049);
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 12px;
                font-weight: bold;
            }
            .stats {
                display: grid;
                grid-template-columns: 1fr 1fr 1fr;
                gap: 10px;
                margin-top: 15px;
            }
            .stat-box {
                background: #f9f9f9;
                padding: 10px;
                border-radius: 4px;
                text-align: center;
            }
            .stat-value { font-size: 20px; font-weight: bold; color: #333; }
            .stat-label { font-size: 12px; color: #999; }
            .sent { color: #4CAF50; }
            .pending { color: #FF9800; }
            .failed { color: #f44336; }
            .status-badge {
                display: inline-block;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
                margin-top: 10px;
            }
            .status-active { background: #c8e6c9; color: #2e7d32; }
            .status-paused { background: #fff3e0; color: #e65100; }
            .account-badge {
                display: inline-block;
                padding: 4px 8px;
                background: #e3f2fd;
                color: #1976d2;
                border-radius: 4px;
                font-size: 11px;
                margin-bottom: 10px;
            }
            .empty-state {
                text-align: center;
                padding: 40px;
                color: #999;
            }
            .refresh-info {
                font-size: 12px;
                color: #999;
                margin-top: 20px;
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📧 Ken Research - Campaign Dashboard</h1>
                <p style="color: #666;">ABM Satellite Outreach Campaign Manager</p>
                <div class="refresh-info">Last updated: <span id="timestamp"></span></div>
            </div>
    """

    if not campaigns:
        html += """
            <div class="empty-state">
                <p>No campaigns yet.</p>
                <p style="margin-top: 10px; color: #ccc;">Create a campaign with: <code>python campaign_manager.py create</code></p>
            </div>
        """
    else:
        html += '<div class="campaigns-grid">'

        for campaign in campaigns:
            brief = campaign["brief"]
            progress = campaign["progress"]

            sent_pct = (progress["sent"] / progress["total_recipients"] * 100) if progress["total_recipients"] > 0 else 0

            html += f"""
            <div class="campaign-card">
                <div class="campaign-title">{brief['name']}</div>
                <div class="account-badge">{brief['account_name']}</div>
                <div class="campaign-meta">
                    ID: {campaign['id']}<br>
                    Created: {brief['created_at'][:10]}
                </div>

                <div class="progress-bar">
                    <div class="progress-fill" style="width: {sent_pct}%;">
                        {int(sent_pct)}%
                    </div>
                </div>

                <div class="stats">
                    <div class="stat-box">
                        <div class="stat-value sent">{progress['sent']}</div>
                        <div class="stat-label">SENT</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value pending">{progress['pending']}</div>
                        <div class="stat-label">PENDING</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value failed">{progress['failed']}</div>
                        <div class="stat-label">FAILED</div>
                    </div>
                </div>

                <div style="margin-top: 15px; font-size: 12px; color: #666;">
                    <strong>Step:</strong> {progress['current_step']}/{len(brief['email_sequences'])}<br>
                    <strong>Updated:</strong> {progress['last_update'][:10]} {progress['last_update'][11:19]}
                </div>

                <div class="status-badge status-active">
                    ● {brief['status'].upper()}
                </div>
            </div>
            """

        html += '</div>'

    html += """
        </div>
        <script>
            function updateTimestamp() {
                document.getElementById('timestamp').textContent = new Date().toLocaleString();
            }
            updateTimestamp();
            setInterval(updateTimestamp, 1000);
        </script>
    </body>
    </html>
    """

    return render_template_string(html)

@app.route('/api/campaigns')
def api_campaigns():
    """API endpoint for campaign data"""
    campaigns = get_all_campaigns()
    return jsonify(campaigns)

@app.route('/api/campaign/<campaign_id>')
def api_campaign_detail(campaign_id):
    """API endpoint for single campaign details"""
    campaign_folder = CAMPAIGNS_DIR / campaign_id

    if not campaign_folder.exists():
        return jsonify({"error": "Campaign not found"}), 404

    brief_path = campaign_folder / "brief.json"
    progress_path = campaign_folder / "progress.json"

    if not (brief_path.exists() and progress_path.exists()):
        return jsonify({"error": "Campaign data missing"}), 404

    with open(brief_path) as f:
        brief = json.load(f)
    with open(progress_path) as f:
        progress = json.load(f)

    return jsonify({
        "id": campaign_id,
        "brief": brief,
        "progress": progress
    })

if __name__ == "__main__":
    print("\n" + "="*60)
    print("Dashboard starting on http://localhost:5000")
    print("="*60 + "\n")
    app.run(debug=True, host="localhost", port=5000)
