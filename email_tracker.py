"""
Email Open Rate Tracker
Tracks pixel loads (email opens) via GET request
Stores opens in SQLite database
Agent queries this database to update progress
"""

from flask import Flask, request, send_file
from datetime import datetime
import sqlite3
import json
import os
from pathlib import Path
from io import BytesIO

app = Flask(__name__)
DB_PATH = 'email_opens.db'

# Initialize database
def init_db():
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

init_db()

# 1x1 transparent PNG pixel (1 byte)
PIXEL = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
    b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)

@app.route('/track/pixel', methods=['GET'])
def track_pixel():
    """Receive pixel request and log open"""
    campaign_id = request.args.get('campaign_id', 'unknown')
    recipient = request.args.get('recipient', 'unknown')
    step = request.args.get('step', '0')
    user_agent = request.headers.get('User-Agent', '')
    ip_address = request.remote_addr
    timestamp = datetime.utcnow().isoformat()

    # Log to database
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO opens (campaign_id, recipient, step, timestamp, user_agent, ip_address)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (campaign_id, recipient, int(step), timestamp, user_agent, ip_address))
    conn.commit()
    conn.close()

    # Return 1x1 transparent PNG
    return send_file(BytesIO(PIXEL), mimetype='image/png')

@app.route('/api/opens', methods=['GET'])
def get_opens():
    """Query opens since timestamp (agent uses this)"""
    campaign_id = request.args.get('campaign_id', '')
    since = request.args.get('since', '2000-01-01T00:00:00')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if campaign_id:
        c.execute('''
            SELECT campaign_id, recipient, step, timestamp, user_agent, ip_address
            FROM opens
            WHERE campaign_id = ? AND timestamp > ?
            ORDER BY timestamp DESC
        ''', (campaign_id, since))
    else:
        c.execute('''
            SELECT campaign_id, recipient, step, timestamp, user_agent, ip_address
            FROM opens
            WHERE timestamp > ?
            ORDER BY timestamp DESC
        ''', (since,))

    rows = c.fetchall()
    conn.close()

    opens = [
        {
            'campaign_id': row[0],
            'recipient': row[1],
            'step': row[2],
            'timestamp': row[3],
            'user_agent': row[4],
            'ip_address': row[5]
        }
        for row in rows
    ]

    return {'opens': opens, 'count': len(opens)}

@app.route('/health', methods=['GET'])
def health():
    """Health check for Render"""
    return {'status': 'ok'}, 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
