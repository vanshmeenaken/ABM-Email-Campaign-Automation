"""Secure unsubscribe tokens and email normalization helpers."""

import os

from itsdangerous import BadData, URLSafeSerializer


TOKEN_SALT = "ken-research-newsletter-unsubscribe-v1"
DEFAULT_SCOPE = "all_newsletters"


class InvalidUnsubscribeToken(ValueError):
    """Raised when an unsubscribe token is missing, invalid, or incomplete."""


def normalize_email(email):
    return (email or "").strip().lower()


def _secret(secret=None):
    value = secret or os.getenv("UNSUBSCRIBE_SECRET_KEY") or os.getenv("FLASK_SECRET_KEY")
    if not value:
        raise RuntimeError("UNSUBSCRIBE_SECRET_KEY or FLASK_SECRET_KEY must be configured.")
    return value


def create_unsubscribe_token(email, campaign_id="", scope=DEFAULT_SCOPE, secret=None):
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        raise ValueError("A valid recipient email is required.")
    serializer = URLSafeSerializer(_secret(secret), salt=TOKEN_SALT)
    return serializer.dumps({"email": normalized, "campaign_id": campaign_id or "", "scope": scope})


def read_unsubscribe_token(token, secret=None):
    try:
        payload = URLSafeSerializer(_secret(secret), salt=TOKEN_SALT).loads(token)
    except BadData as exc:
        raise InvalidUnsubscribeToken("This unsubscribe link is invalid.") from exc

    email = normalize_email(payload.get("email")) if isinstance(payload, dict) else ""
    if not email or "@" not in email:
        raise InvalidUnsubscribeToken("This unsubscribe link is incomplete.")
    return {
        "email": email,
        "campaign_id": str(payload.get("campaign_id") or ""),
        "scope": str(payload.get("scope") or DEFAULT_SCOPE),
    }


def masked_email(email):
    normalized = normalize_email(email)
    if "@" not in normalized:
        return normalized
    local, domain = normalized.split("@", 1)
    if len(local) <= 2:
        visible = local[:1]
    else:
        visible = local[:2]
    return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"
