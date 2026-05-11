"""
Configuration for Email Tracker & Campaign Manager
Manages tracker URLs across dev/staging/production
"""

import os
from pathlib import Path

ENV = os.getenv("ENV", "development")

# Tracker URLs by environment
TRACKER_URLS = {
    "development": "http://localhost:5000",
    "staging": os.getenv("TRACKER_URL_STAGING", "http://localhost:5000"),
    "production": os.getenv("TRACKER_URL_PRODUCTION", "https://ken-email-tracker.onrender.com")
}

TRACKER_URL = TRACKER_URLS.get(ENV, TRACKER_URLS["development"])

# Database paths
PROJECT_ROOT = Path(__file__).parent
CAMPAIGNS_DIR = PROJECT_ROOT / "campaigns"
CAMPAIGNS_DB = PROJECT_ROOT / "campaigns.db"
OPENS_DB = PROJECT_ROOT / "email_opens.db"

# Settings
TRACKER_TIMEOUT = 5  # seconds
MAX_RETRIES = 3
