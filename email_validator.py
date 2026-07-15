#!/usr/bin/env python3
"""
Email Validator - Bouncify API integration
Validates email addresses before sending
"""

import requests
from datetime import datetime

BOUNCIFY_API_URL = "https://api.bouncify.io/v1/verify"
BOUNCIFY_API_KEY = "cmynmx1adw1cnb1b11zchk6lpk6dux0d"

def validate_email(email):
    """
    Validate email using Bouncify API
    Returns: dict with result, status, and reason
    """
    try:
        response = requests.get(
            BOUNCIFY_API_URL,
            params={"apikey": BOUNCIFY_API_KEY, "email": email},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            result = data.get("result", "unknown").lower()
            message = data.get("message", "")

            return {
                "email": email,
                "valid": result in ["deliverable", "accept_all", "unknown"],
                "status": result,
                "message": message,
                "details": {
                    "free_email": bool(data.get("free_email")),
                    "role": bool(data.get("role")),
                    "disposable": bool(data.get("disposable")),
                    "spamtrap": bool(data.get("spamtrap")),
                    "accept_all": bool(data.get("accept_all")),
                }
            }
        else:
            return {
                "email": email,
                "valid": False,
                "status": "validation_error",
                "message": f"API error: {response.status_code}",
                "details": {}
            }

    except requests.exceptions.Timeout:
        return {
            "email": email,
            "valid": False,
            "status": "timeout",
            "message": "Validation timeout",
            "details": {}
        }
    except Exception as e:
        return {
            "email": email,
            "valid": False,
            "status": "error",
            "message": str(e),
            "details": {}
        }

def validate_recipients(recipients):
    """
    Validate multiple recipients
    Returns: dict with valid, invalid, and rejected lists
    """
    valid = []
    invalid = []

    for recipient in recipients:
        result = validate_email(recipient)
        if result["valid"]:
            valid.append(recipient)
        else:
            invalid.append({
                "email": recipient,
                "reason": result["message"],
                "status": result["status"]
            })

    return {
        "valid": valid,
        "invalid": invalid,
        "valid_count": len(valid),
        "invalid_count": len(invalid),
        "total": len(recipients)
    }
