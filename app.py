#!/usr/bin/env python3
"""
Ken Research - Email Campaign Web App
Unified Flask app combining email sending, tracking, and campaign dashboard.
"""

import base64
import mimetypes
import os
import json
import socket
import threading
from datetime import datetime, timedelta
from io import BytesIO

import psycopg2
import psycopg2.extras
from flask import Flask, request, send_file, send_from_directory, render_template, redirect, url_for, jsonify, flash
from dotenv import load_dotenv

load_dotenv()

from send_email import send_email

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

DATABASE_URL = os.getenv("DATABASE_URL")
BOUNCIFY_API_KEY = os.getenv("BOUNCIFY_API_KEY", "")
NEWSLETTER_ASSETS_DIR = os.path.join(app.root_path, "assets", "newsletter")
NEWSLETTER_ASSET_FILES = {
    "kensight-newsletter-hero.svg",
    "kensight-social-icons.svg",
    "ken-research-footer-mark.svg",
    "kensight-newsletter-hero.png",
    "kensight-social-icons.png",
    "kensight-cta.png",
    "ken-research-footer-mark.png",
    "mailmodo-hero-banner.jpg",
    "mailmodo-instagram.png",
    "mailmodo-twitter.png",
    "mailmodo-linkedin.png",
    "mailmodo-youtube.png",
    "mailmodo-website.png",
    "mailmodo-footer-logo.png",
}
NEWSLETTER_INLINE_ASSET_FILES = (
    "mailmodo-hero-banner.jpg",
    "mailmodo-instagram.png",
    "mailmodo-twitter.png",
    "mailmodo-linkedin.png",
    "mailmodo-youtube.png",
    "mailmodo-website.png",
    "mailmodo-footer-logo.png",
)

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
    "5": "Shreya Gupta",
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

_JUNK = {"na", "n/a", "-", "--", ""}


def _is_url(s):
    sl = s.lower()
    return s.startswith("http") or "linkedin.com" in sl or (
        "." in s and "/" in s and "@" not in s
    )


def _is_phone(s):
    stripped = s.replace("+", "").replace(" ", "").replace("-", "")
    return stripped.isdigit() and len(stripped) >= 7


def _find_col(headers, *keywords):
    for i, h in enumerate(headers):
        if any(k in h.lower() for k in keywords):
            return i
    return None


def _row_to_recipient(parts, email_col, name_col, company_col, designation_col):
    """Build a recipient dict from one row of cell values, given column indices."""
    email = parts[email_col].strip().lower() if email_col is not None and email_col < len(parts) else ""
    if not email or email in _JUNK or "@" not in email:
        return None

    raw_name = parts[name_col].strip() if name_col is not None and name_col < len(parts) else ""
    first_name = raw_name.split()[0] if raw_name else ""

    company = parts[company_col].strip() if company_col is not None and company_col < len(parts) else ""
    if company.lower() in _JUNK:
        company = ""

    designation = parts[designation_col].strip() if designation_col is not None and designation_col < len(parts) else ""
    if designation.lower() in _JUNK:
        designation = ""

    return {"email": email, "first_name": first_name, "company": company, "designation": designation}


def parse_recipients(raw_text):
    """Parse recipient lines into dicts.

    Supports:
    1. Header-aware tab/comma-separated (paste from Excel/Sheets with column headers).
       Recognises columns: Email, Full Name / Name, Company Name / Company, Designation / Title.
       Skips rows where the email cell is empty or "NA".
    2. Headerless tab-separated — auto-detects email column by @, heuristically
       picks name and company from remaining text fields.
    3. Simple comma-separated: "Name, Company, email" or "Name, email" or "email".

    Returns list of {"email": ..., "first_name": ..., "company": ..., "designation": ...}
    """
    lines = [l for l in raw_text.splitlines() if l.strip()]
    if not lines:
        return []

    result = []

    # --- Detect if first line is a header row (no @ in it) ---
    first = lines[0]
    delimiter = "\t" if "\t" in first else ","
    first_parts = [p.strip() for p in first.split(delimiter)]
    has_header = "@" not in first and any(
        kw in first.lower() for kw in ("email", "name", "company", "linkedin", "designation", "title")
    )

    if has_header:
        headers = [p.lower().strip() for p in first_parts]
        email_col       = _find_col(headers, "email")
        name_col        = _find_col(headers, "full name", "name", "prospect_full")
        company_col     = _find_col(headers, "company name", "company", "prospect_company", "organisation")
        designation_col = _find_col(headers, "designation", "title", "job title", "position")

        if email_col is None:
            # No email column found in header — fall through to heuristic
            has_header = False
        else:
            for line in lines[1:]:
                parts = [p.strip() for p in line.split(delimiter)]
                rec = _row_to_recipient(parts, email_col, name_col, company_col, designation_col)
                if rec:
                    result.append(rec)
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

        result.append({"email": email, "first_name": first_name, "company": company, "designation": ""})

    return result


def parse_recipients_excel(file_storage):
    """Parse an uploaded Excel (.xlsx/.xls) or CSV file into recipient dicts.

    Expects a header row with columns: Email, Name (or Full Name), Company (or Company Name),
    Designation (or Title) — column order doesn't matter, header names are matched case-insensitively.

    Returns list of {"email": ..., "first_name": ..., "company": ..., "designation": ...}
    """
    filename = (file_storage.filename or "").lower()
    rows = []

    if filename.endswith((".xlsx", ".xls")):
        import openpyxl
        from io import BytesIO
        wb = openpyxl.load_workbook(BytesIO(file_storage.read()), data_only=True, read_only=True)
        ws = wb.active
        for row in ws.iter_rows(values_only=True):
            rows.append(["" if c is None else str(c).strip() for c in row])
    elif filename.endswith(".csv"):
        import csv, io
        content = file_storage.read().decode("utf-8", errors="ignore")
        rows = [[c.strip() for c in row] for row in csv.reader(io.StringIO(content))]
    else:
        return []

    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        return []

    headers = [h.lower().strip() for h in rows[0]]
    email_col       = _find_col(headers, "email")
    name_col        = _find_col(headers, "full name", "name", "prospect_full")
    company_col     = _find_col(headers, "company name", "company", "prospect_company", "organisation")
    designation_col = _find_col(headers, "designation", "title", "job title", "position")

    if email_col is None:
        return []

    result = []
    for parts in rows[1:]:
        rec = _row_to_recipient(parts, email_col, name_col, company_col, designation_col)
        if rec:
            result.append(rec)
    return result


def personalize(text, first_name, company="", designation=""):
    """Replace {First Name}, {Company}, {Designation}/{Title}, and bracket variants."""
    name = first_name or ""
    comp = company or ""
    desig = designation or ""
    for placeholder in ("{First Name}", "{first_name}", "{Name}", "{name}",
                        "[First Name]", "[first name]", "[Name]", "[name]"):
        text = text.replace(placeholder, name)
    for placeholder in ("{Company}", "{company}", "{Company Name}", "{company name}",
                        "[Company]", "[company]", "[Company Name]", "[company name]"):
        text = text.replace(placeholder, comp)
    for placeholder in ("{Designation}", "{designation}", "{Title}", "{title}",
                        "{Job Title}", "{job title}",
                        "[Designation]", "[designation]", "[Title]", "[title]",
                        "[Job Title]", "[job title]"):
        text = text.replace(placeholder, desig)
    return text


def apply_bold_markdown(text):
    """Convert **bold** markers (inserted via the Bold button) into <strong> tags."""
    import re
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)


def apply_italic_markdown(text):
    """Convert *italic* markers (inserted via the Italic button) into <em> tags.
    Must run AFTER apply_bold_markdown — bold's ** pairs are consumed first, leaving
    only single asterisks behind so this can't misparse a ** pair as two * pairs."""
    import re
    return re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)


def apply_link_markdown(text):
    """Convert [text](url) markers (inserted via the Link button) into <a> tags."""
    import re
    return re.sub(
        r'\[(.+?)\]\((https?://[^\s)]+)\)',
        r'<a href="\2" target="_blank" style="color:#2563eb;text-decoration:underline;">\1</a>',
        text,
    )


def plain_to_html(text):
    """Convert plain text body to HTML if it contains no HTML tags. Always applies
    [text](url) link, **bold**, then *italic* markdown conversion first (checked
    against the pre-conversion text so formatted plain-text emails still get <br>
    line breaks)."""
    import re
    already_html = bool(re.search(r'<[a-zA-Z/]', text))
    text = apply_link_markdown(text)
    text = apply_bold_markdown(text)
    text = apply_italic_markdown(text)
    if already_html:
        return text  # already HTML, leave structure untouched
    # Preserve paragraphs and line breaks
    paragraphs = text.split('\n\n')
    parts = []
    for para in paragraphs:
        lines = para.replace('\n', '<br>')
        parts.append(f"<p>{lines}</p>")
    return '\n'.join(parts)


def format_inline_html(text):
    """Apply lightweight markdown formatting without wrapping in <p> tags."""
    text = apply_link_markdown(text or "")
    text = apply_bold_markdown(text)
    text = apply_italic_markdown(text)
    return text


def parse_bullet_lines(text):
    """Parse one bullet per line, tolerating -, *, and bullet prefixes."""
    items = []
    for raw in (text or "").splitlines():
        item = raw.strip()
        if not item:
            continue
        if item[:1] in {"-", "*", "•"}:
            item = item[1:].strip()
        if item:
            items.append(item)
    return items


def newsletter_asset_url(asset_base_url, filename):
    if (asset_base_url or "").strip().lower() == "cid":
        return f"cid:{filename}"
    base = (asset_base_url or "").strip().rstrip("/")
    return f"{base}/assets/newsletter/{filename}" if base else f"/assets/newsletter/{filename}"


def render_kensight_newsletter(form, asset_base_url=""):
    """Render the newsletter template into email-safe HTML."""
    def value(name, default=""):
        return (form.get(name, default) or "").strip()

    greeting = value("newsletter_greeting", "Hi {first_name},")
    intro_1 = value(
        "newsletter_intro_1",
        "Welcome to KenSight, our newsletter for leaders who want to see markets more clearly and act before signals become obvious.",
    )
    intro_2 = value(
        "newsletter_intro_2",
        "Ken Research is a global market research and consulting firm helping strategy teams make sharper decisions on market attractiveness, growth strategy, expansion, and competitive positioning.",
    )

    stat_1_value = value("newsletter_stat_1_value", "100,000+")
    stat_1_label = value("newsletter_stat_1_label", "MARKET REPORTS")
    stat_2_value = value("newsletter_stat_2_value", "200,000+")
    stat_2_label = value("newsletter_stat_2_label", "INDUSTRY EXPERTS")
    stat_3_value = value("newsletter_stat_3_value", "70+")
    stat_3_label = value("newsletter_stat_3_label", "COUNTRIES")

    services_intro = value(
        "newsletter_services_intro",
        "We help clients navigate growth through four core services:",
    )
    services_items = parse_bullet_lines(value(
        "newsletter_services_list",
        "- Data-driven strategy consulting that turns market intelligence into clear roadmaps.\n"
        "- In-depth market intelligence reports decoding market size, competition, pricing, and regulations.\n"
        "- End-to-end survey solutions delivering first-hand insights.\n"
        "- A curated network of 200,000+ industry professionals for complex business questions.",
    ))

    insights_intro = value(
        "newsletter_insights_intro",
        "Through KenSight, we bring together our expertise into clear, relevant insights delivered straight to your inbox.",
    )
    insights_heading = value(
        "newsletter_insights_heading",
        "Each edition will help you spot:",
    )
    insights_items = parse_bullet_lines(value(
        "newsletter_insights_list",
        "- Market shifts worth watching\n"
        "- Metrics that reframe the debate\n"
        "- The consulting perspective behind the numbers\n"
        "- Early signals before they hit consensus",
    ))

    signoff = value(
        "newsletter_signoff",
        "The first edition lands soon.\n-- Ken Research Team",
    )
    cta_text = value("newsletter_cta_text", "Explore Latest Insights")
    cta_url = value("newsletter_cta_url", "https://www.kenresearch.com")
    brand_url = value("newsletter_brand_url", cta_url or "https://www.kenresearch.com")

    footer_line_1 = value("newsletter_footer_line_1", "&copy; 2026 KenSight by Ken Research")
    footer_line_2 = value("newsletter_footer_line_2", "India | UAE | Indonesia | Qatar")
    footer_link_text = value("newsletter_footer_link_text", "Prefer Ken Research on Google")
    footer_link_url = value("newsletter_footer_link_url", "https://www.google.com/search?q=Ken+Research")

    social_links = [
        ("mailmodo-instagram.png", value("newsletter_social_instagram", "https://www.instagram.com/kenresearch")),
        ("mailmodo-twitter.png", value("newsletter_social_x", "https://x.com/kenresearch")),
        ("mailmodo-linkedin.png", value("newsletter_social_linkedin", "https://www.linkedin.com/company/ken-research")),
        ("mailmodo-youtube.png", value("newsletter_social_youtube", "https://www.youtube.com/@kenresearch")),
        ("mailmodo-website.png", value("newsletter_social_website", "https://www.kenresearch.com")),
    ]
    social_html = "".join(
        f"""
                <td align="center" width="50" style="padding:0 7px;">
                  <a href="{url}" target="_blank" style="text-decoration:none;">
                    <img src="{newsletter_asset_url(asset_base_url, filename)}" width="36" height="36" alt=""
                         style="display:block;width:36px;height:36px;border:0;outline:none;text-decoration:none;" />
                  </a>
                </td>
        """
        for filename, url in social_links
    )
    hero_url = newsletter_asset_url(asset_base_url, "mailmodo-hero-banner.jpg")
    footer_mark_url = newsletter_asset_url(asset_base_url, "mailmodo-footer-logo.png")

    services_html = "".join(
        f'<li style="margin:0 0 10px 0;">{format_inline_html(item)}</li>'
        for item in services_items
    )
    insights_html = "".join(
        f'<li style="margin:0 0 8px 0;">{format_inline_html(item)}</li>'
        for item in insights_items
    )

    return f"""
    <div style="display:none;font-size:1px;color:#f5f5f5;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">
      KenSight by Ken Research
    </div>
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#f7f7f7" style="width:100%;background-color:#f7f7f7;margin:0;padding:0;">
      <tr>
        <td align="center" bgcolor="#f7f7f7" style="padding:0 12px;background-color:#f7f7f7;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="640" bgcolor="#ffffff" style="max-width:640px;width:100%;background:#ffffff;background-color:#ffffff;">
            <tr>
              <td align="center" bgcolor="#ffffff" style="padding:4px 0 18px 0;background-color:#ffffff;">
                <a href="{brand_url}" target="_blank" style="text-decoration:none;">
                  <img src="{hero_url}" width="616" height="166" alt="KenSight by Ken Research - Read the market before it moves"
                       style="display:block;width:616px;max-width:100%;height:auto;border:0;outline:none;text-decoration:none;" />
                </a>
              </td>
            </tr>

            <tr>
              <td bgcolor="#ffffff" style="padding:0 28px 6px 28px;background-color:#ffffff;font-family:Georgia, 'Times New Roman', serif;font-size:28px;line-height:40px;color:#111827;">
                {format_inline_html(greeting)}
              </td>
            </tr>

            <tr>
              <td bgcolor="#ffffff" style="padding:0 28px 6px 28px;background-color:#ffffff;font-family:Georgia, 'Times New Roman', serif;font-size:19px;line-height:32px;color:#111827;">
                {plain_to_html(intro_1)}
                {plain_to_html(intro_2)}
              </td>
            </tr>

            <tr>
              <td bgcolor="#ffffff" style="padding:18px 28px 6px 28px;background-color:#ffffff;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;background:#353c3c;">
                  <tr>
                    <td align="center" style="width:33.33%;padding:18px 8px;border-right:1px solid #515858;">
                      <div style="font-family:Arial, sans-serif;font-size:18px;line-height:22px;font-weight:700;color:#ffffff;">{format_inline_html(stat_1_value)}</div>
                      <div style="font-family:Arial, sans-serif;font-size:11px;line-height:14px;font-weight:700;letter-spacing:0.8px;color:#d1d5db;padding-top:6px;">{format_inline_html(stat_1_label)}</div>
                    </td>
                    <td align="center" style="width:33.33%;padding:18px 8px;border-right:1px solid #515858;">
                      <div style="font-family:Arial, sans-serif;font-size:18px;line-height:22px;font-weight:700;color:#ffffff;">{format_inline_html(stat_2_value)}</div>
                      <div style="font-family:Arial, sans-serif;font-size:11px;line-height:14px;font-weight:700;letter-spacing:0.8px;color:#d1d5db;padding-top:6px;">{format_inline_html(stat_2_label)}</div>
                    </td>
                    <td align="center" style="width:33.33%;padding:18px 8px;">
                      <div style="font-family:Arial, sans-serif;font-size:18px;line-height:22px;font-weight:700;color:#ffffff;">{format_inline_html(stat_3_value)}</div>
                      <div style="font-family:Arial, sans-serif;font-size:11px;line-height:14px;font-weight:700;letter-spacing:0.8px;color:#d1d5db;padding-top:6px;">{format_inline_html(stat_3_label)}</div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <tr>
              <td bgcolor="#ffffff" style="padding:8px 28px 0 28px;background-color:#ffffff;font-family:Georgia, 'Times New Roman', serif;font-size:19px;line-height:32px;color:#111827;">
                {plain_to_html(services_intro)}
              </td>
            </tr>
            <tr>
              <td bgcolor="#ffffff" style="padding:0 40px 0 48px;background-color:#ffffff;font-family:Georgia, 'Times New Roman', serif;font-size:18px;line-height:30px;color:#111827;">
                <ul style="margin:0;padding-left:18px;">
                  {services_html}
                </ul>
              </td>
            </tr>

            <tr>
              <td bgcolor="#ffffff" style="padding:6px 28px 0 28px;background-color:#ffffff;font-family:Georgia, 'Times New Roman', serif;font-size:19px;line-height:32px;color:#111827;">
                {plain_to_html(insights_intro)}
                {plain_to_html(insights_heading)}
              </td>
            </tr>
            <tr>
              <td bgcolor="#ffffff" style="padding:0 40px 0 48px;background-color:#ffffff;font-family:Georgia, 'Times New Roman', serif;font-size:18px;line-height:30px;color:#111827;">
                <ul style="margin:0;padding-left:18px;">
                  {insights_html}
                </ul>
              </td>
            </tr>

            <tr>
              <td bgcolor="#ffffff" style="padding:10px 28px 0 28px;background-color:#ffffff;font-family:Georgia, 'Times New Roman', serif;font-size:19px;line-height:32px;color:#111827;">
                {plain_to_html(signoff)}
              </td>
            </tr>

            <tr>
              <td align="center" bgcolor="#ffffff" style="padding:0;background-color:#ffffff;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#ffffff" style="width:100%;background-color:#ffffff;">
                  <tr>
                    <td align="center" bgcolor="#ffffff" style="padding:36px 28px 58px 28px;background-color:#ffffff;">
                      <!--[if mso]>
                      <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word"
                        href="{cta_url}" style="height:49px;v-text-anchor:middle;width:275px;" arcsize="50%" strokecolor="#bd2029" fillcolor="#bd2029">
                        <w:anchorlock/>
                        <center style="color:#ffffff;font-family:Arial, Helvetica, sans-serif;font-size:18px;font-weight:700;">
                          {format_inline_html(cta_text)}
                        </center>
                      </v:roundrect>
                      <![endif]-->
                      <!--[if !mso]><!-->
                      <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" width="275" style="width:275px;border-collapse:separate;">
                        <tr>
                          <td align="center" bgcolor="#bd2029" height="49" style="height:49px;background-color:#bd2029;border-radius:999px;">
                            <a href="{cta_url}" target="_blank"
                               style="display:block;width:275px;height:49px;color:#ffffff;text-decoration:none;font-family:Arial, Helvetica, sans-serif;
                                      font-size:18px;line-height:49px;font-weight:700;text-align:center;border-radius:999px;">
                              {format_inline_html(cta_text)}
                            </a>
                          </td>
                        </tr>
                      </table>
                      <!--<![endif]-->
                    </td>
                  </tr>
                  <tr>
                    <td align="center" bgcolor="#ffffff" style="padding:0 20px 84px 20px;background-color:#ffffff;">
                      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 auto;">
                        <tr>
                          {social_html}
                        </tr>
                      </table>
                    </td>
                  </tr>
                  <tr>
                    <td align="center" bgcolor="#ffffff" style="padding:0 28px 28px 28px;background-color:#ffffff;font-family:Arial, Helvetica, sans-serif;color:#000000;">
                      <div style="font-size:14px;line-height:20px;">{format_inline_html(footer_line_1)}</div>
                      <div style="font-size:14px;line-height:20px;padding-top:8px;">{format_inline_html(footer_line_2)}</div>
                      <div style="font-size:14px;line-height:20px;padding-top:8px;">
                        <a href="{footer_link_url}" target="_blank" style="color:#ff1f1f;text-decoration:underline;">{format_inline_html(footer_link_text)}</a>
                      </div>
                      <img src="{footer_mark_url}" width="30" height="30" alt="Ken Research"
                           style="display:block;width:30px;height:30px;border:0;outline:none;text-decoration:none;margin:16px auto 0 auto;" />
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    """


def render_kensight_pov_newsletter(form, asset_base_url=""):
    """Render the compact POV/download KenSight newsletter template."""
    def value(name, default=""):
        return (form.get(name, default) or "").strip()

    greeting = value("pov_greeting", "Hi {first_name},")
    brand_url = value("pov_brand_url", "https://www.kenresearch.com")
    intro_1 = value(
        "pov_intro_1",
        "Most automotive plants already have the robots, AGVs and machine vision systems. What's separating leaders from laggards now is whether those systems talk to each other.",
    )
    intro_2 = value(
        "pov_intro_2",
        "Global industrial automation spend has grown from $175 billion in 2020 toward a projected $417 billion by 2030. However, plants still running on siloed control, execution and analytics layers are seeing slower feedback loops, weaker traceability and higher integration risk, even with modern equipment on the floor.",
    )
    intro_3 = value(
        "pov_intro_3",
        "The edge has moved from owning machinery to owning the stack.",
    )
    article_title = value("pov_article_title", "Automotive Automation: From Upgrade to Survival Strategy")
    article_url = value("pov_article_url", "https://www.kenresearch.com")
    article_suffix = value(
        "pov_article_suffix",
        "traces this shift for automotive OEMs, from equipment-led automation to integrated, autonomous operating models.",
    )
    download_text = value("pov_download_text", "Download the POV")
    download_url = value("pov_download_url", article_url or "https://www.kenresearch.com")
    signoff = value("pov_signoff", "Regards,\nKen Research Team")

    footer_line_1 = value("pov_footer_line_1", "India | UAE | Indonesia | Qatar")
    footer_line_2 = value("pov_footer_line_2", "&copy;2026 KenSight by Ken Research")
    footer_link_text = value("pov_footer_link_text", "Prefer Ken Research on Google")
    footer_link_url = value("pov_footer_link_url", "https://www.google.com/search?q=Ken+Research")
    unsubscribe_url = value("pov_unsubscribe_url", "https://www.kenresearch.com")

    social_links = [
        ("mailmodo-website.png", value("pov_social_website", "https://www.kenresearch.com")),
        ("mailmodo-linkedin.png", value("pov_social_linkedin", "https://www.linkedin.com/company/ken-research")),
        ("mailmodo-twitter.png", value("pov_social_x", "https://x.com/kenresearch")),
        ("mailmodo-youtube.png", value("pov_social_youtube", "https://www.youtube.com/@kenresearch")),
        ("mailmodo-instagram.png", value("pov_social_instagram", "https://www.instagram.com/kenresearch")),
    ]
    social_html = "".join(
        f"""
                        <td align="center" width="42" style="padding:0 7px;">
                          <a href="{url}" target="_blank" style="text-decoration:none;">
                            <img src="{newsletter_asset_url(asset_base_url, filename)}" width="22" height="22" alt=""
                                 style="display:block;width:22px;height:22px;border:0;outline:none;text-decoration:none;" />
                          </a>
                        </td>
        """
        for filename, url in social_links
    )
    hero_url = newsletter_asset_url(asset_base_url, "mailmodo-hero-banner.jpg")

    return f"""
    <div style="display:none;font-size:1px;color:#f5f5f5;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">
      KenSight by Ken Research
    </div>
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#f7f7fb" style="width:100%;background-color:#f7f7fb;margin:0;padding:0;">
      <tr>
        <td align="center" bgcolor="#f7f7fb" style="padding:24px 12px;background-color:#f7f7fb;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="456" bgcolor="#ffffff" style="width:456px;max-width:456px;background:#ffffff;background-color:#ffffff;">
            <tr>
              <td align="center" bgcolor="#ffffff" style="padding:16px 18px 24px 18px;background-color:#ffffff;">
                <a href="{brand_url}" target="_blank" style="text-decoration:none;">
                  <img src="{hero_url}" width="420" height="113" alt="KenSight by Ken Research - Read the market before it moves"
                       style="display:block;width:420px;max-width:100%;height:auto;border:0;outline:none;text-decoration:none;" />
                </a>
              </td>
            </tr>
            <tr>
              <td bgcolor="#ffffff" style="padding:0 14px 0 14px;background-color:#ffffff;font-family:Arial, Helvetica, sans-serif;font-size:12px;line-height:19px;color:#000000;">
                <p style="margin:0 0 20px 0;">{format_inline_html(greeting)}</p>
                {plain_to_html(intro_1)}
                {plain_to_html(intro_2)}
                {plain_to_html(intro_3)}
                <p style="margin:0 0 20px 0;">
                  Our latest POV, <a href="{article_url}" target="_blank" style="color:#ff1f1f;text-decoration:underline;">{format_inline_html(article_title)}</a>, {format_inline_html(article_suffix)}
                </p>
                <p style="margin:0 0 20px 0;">
                  <a href="{download_url}" target="_blank" style="color:#ff1f1f;text-decoration:underline;">{format_inline_html(download_text)}</a>
                </p>
                {plain_to_html(signoff)}
              </td>
            </tr>
            <tr>
              <td align="center" bgcolor="#ffffff" style="padding:48px 14px 34px 14px;background-color:#ffffff;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:0 auto;">
                  <tr>
                    {social_html}
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td align="center" bgcolor="#ffffff" style="padding:0 14px 24px 14px;background-color:#ffffff;font-family:Arial, Helvetica, sans-serif;color:#000000;">
                <div style="font-size:10px;line-height:15px;">{format_inline_html(footer_line_1)}</div>
                <div style="font-size:10px;line-height:15px;padding-top:6px;">{format_inline_html(footer_line_2)}</div>
                <div style="font-size:10px;line-height:15px;padding-top:6px;">
                  <a href="{footer_link_url}" target="_blank" style="color:#ff1f1f;text-decoration:underline;">{format_inline_html(footer_link_text)}</a>
                </div>
              </td>
            </tr>
            <tr>
              <td align="center" bgcolor="#f2f5f8" style="padding:14px 14px 16px 14px;background-color:#f2f5f8;font-family:Arial, Helvetica, sans-serif;color:#9aa7b7;">
                <div style="font-size:9px;line-height:14px;">powered by <span style="color:#5b6b7a;font-weight:700;">mailmodo</span></div>
                <div style="font-size:10px;line-height:15px;padding-top:12px;">
                  <a href="{unsubscribe_url}" target="_blank" style="color:#6b7280;text-decoration:underline;">Unsubscribe</a>
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    """


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


def newsletter_inline_attachments(body):
    """Attach built-in newsletter images inline when the template references them."""
    graph_attachments = []
    for filename in NEWSLETTER_INLINE_ASSET_FILES:
        if f"cid:{filename}" not in body:
            continue
        path = os.path.join(NEWSLETTER_ASSETS_DIR, filename)
        if not os.path.isfile(path):
            print(f"[NEWSLETTER ASSET] Missing inline asset: {filename}")
            continue
        with open(path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")
        graph_attachments.append({
            "name": filename,
            "contentType": mimetypes.guess_type(filename)[0] or "application/octet-stream",
            "contentBytes": content_b64,
            "contentId": filename,
            "isInline": True,
        })
    return graph_attachments


# ---------------------------------------------------------------------------
# Email validation
# ---------------------------------------------------------------------------

def validate_email_bouncify(email):
    """Validate email via Bouncify. Returns (status, result).
    status: 'valid' | 'invalid' | 'risky' | 'unknown'

    Catch-all ("accept_all") domains report 'deliverable' from Bouncify even though
    the receiving server accepts every RCPT TO without actually checking the mailbox
    exists — that's exactly how a dead address on a catch-all domain slips past
    validation and still hard-bounces later. Treat accept_all/disposable as risky
    regardless of the headline result, so it's skipped before ever reaching Graph
    API rather than only being caught after the fact by the bounce-checker.
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
        if resp.status_code != 200:
            return "unknown", f"http_{resp.status_code}"

        data = resp.json()
        result = data.get("result", "unknown")

        is_catch_all = any(
            data.get(k) in (True, "true", "yes", 1)
            for k in ("accept_all", "catch_all", "is_catch_all", "catchall")
        )
        is_disposable = any(
            data.get(k) in (True, "true", "yes", 1)
            for k in ("disposable", "is_disposable")
        )

        if is_disposable:
            return "risky", f"{result} (disposable)"
        if is_catch_all:
            return "risky", f"{result} (catch_all domain - mailbox existence unconfirmed)"

        if result == "deliverable":
            return "valid", result
        elif result == "undeliverable":
            return "invalid", result
        elif result == "risky":
            return "risky", result
        else:
            return "unknown", result
    except Exception:
        return "unknown", "error"


# ---------------------------------------------------------------------------
# Campaign worker
# ---------------------------------------------------------------------------

def bulk_send_worker(campaign_id, account_num, recipients, sequences, tracker_url, lock_key=None):
    """Multi-step campaign sender with full state persistence via Supabase.

    lock_key: defaults to campaign_id (one worker per campaign at a time). Pass a
    distinct key (e.g. f"{campaign_id}:addon:<ts>") for an add-on batch of new
    recipients added to an already-running campaign, so it isn't blocked by the
    main worker's lock — both write to the same campaign's send_details.
    """
    import time, random
    lock_key = lock_key or campaign_id

    with _running_lock:
        if lock_key in _running_campaigns:
            print(f"[SKIP] {lock_key} already running — duplicate thread blocked")
            return
        _running_campaigns.add(lock_key)

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

            # Abort if campaign was paused while we were waiting
            try:
                live_status = _load_progress(campaign_id).get("campaign_status", "active")
                if live_status == "paused":
                    print(f"[{campaign_id}] Paused — aborting worker.")
                    return
            except Exception:
                pass

            print(f"[{campaign_id}] Step {step_num}: sending to {len(need_step)} recipients "
                  f"(skipping {len(recipients) - len(need_step)} already sent/replied)...")

            # Load attachments for this step once (shared across all recipients)
            step_attachments = get_attachments(campaign_id, step_num)

            sends_attempted = 0
            for i, rec in enumerate(need_step):
                email = rec["email"]
                first_name = rec.get("first_name", "")
                company = rec.get("company", "")
                designation = rec.get("designation", "")
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
                                    # Skip invalid and risky only — allow unknown to be sent
                                    if val_status in ("invalid", "risky"):
                                        detail["status"] = "skipped"
                                        detail["skip_reason"] = f"Bouncify: {val_status} ({val_result})"
                                        prog["pending"] = max(0, prog.get("pending", 1) - 1)
                                    break
                            _save_progress(campaign_id, prog)
                        except Exception:
                            pass
                        if val_status in ("invalid", "risky"):
                            print(f"[VALIDATE] Skipping {email} ({val_status}: {val_result})")
                            continue

                    # Check pause flag before each send (catches pause mid-batch)
                    try:
                        if _load_progress(campaign_id).get("campaign_status") == "paused":
                            print(f"[{campaign_id}] Paused mid-step — aborting worker.")
                            return
                    except Exception:
                        pass

                    if sends_attempted > 0:
                        time.sleep(random.uniform(240, 300))  # 4-5 min anti-spam gap
                    sends_attempted += 1

                    p_subject = personalize(subject, first_name, company, designation)
                    p_body = plain_to_html(personalize(body, first_name, company, designation))
                    graph_atts = newsletter_inline_attachments(p_body)

                    # Apply attachments — replace markers in body, build graph list
                    if step_attachments:
                        p_body, uploaded_atts = apply_attachments(p_body, step_attachments)
                        graph_atts.extend(uploaded_atts)

                    result, fail_reason = send_email(
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
                                    detail.pop("fail_reason", None)
                                    if step_num == 1:
                                        prog["sent"] = prog.get("sent", 0) + 1
                                        prog["pending"] = max(0, prog.get("pending", 1) - 1)
                                else:
                                    detail["status"] = "failed"
                                    detail["fail_reason"] = fail_reason or "Graph API error"
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
            _running_campaigns.discard(lock_key)


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
                "designation": r.get("designation", ""),
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

        # Per-step progress — derived from steps_completed so it works for all steps
        current_step = progress.get("current_step", 1)
        current_step_sent = sum(1 for d in send_details if current_step in d.get("steps_completed", []))

        campaigns_info.append({
            "id": cid,
            "name": brief.get("name", cid),
            "account": brief.get("account_name", "—"),
            "status": brief.get("status", "active"),
            "campaign_status": campaign_status,
            "next_step_send_at": next_send_at,
            "next_send_label": next_send_label,
            "sent": sent,
            "current_step_sent": current_step_sent,
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
    recipients_file = request.files.get("recipients_file")
    campaign_id = request.form.get("campaign_id", "").strip() or None
    tracker_url = request.form.get("tracker_url", "http://localhost:5000").strip()
    template_mode = request.form.get("template_mode", "custom").strip() or "custom"

    if not account_num or account_num not in ACCOUNTS:
        flash("Please select a valid account.", "error")
        return redirect(url_for("send_form"))
    if not recipients_raw and not (recipients_file and recipients_file.filename):
        flash("Upload a recipients file or paste recipients manually.", "error")
        return redirect(url_for("send_form"))

    recipients = []
    if recipients_file and recipients_file.filename:
        try:
            recipients = parse_recipients_excel(recipients_file)
        except Exception as e:
            flash(f"Could not read the uploaded file: {e}", "error")
            return redirect(url_for("send_form"))
        if not recipients:
            flash("No valid rows found in the uploaded file. Make sure it has an 'Email' column header.", "error")
            return redirect(url_for("send_form"))
    else:
        recipients = parse_recipients(recipients_raw)
        if not recipients:
            flash("No valid email addresses found in recipients field.", "error")
            return redirect(url_for("send_form"))

    sequences = []
    subject_1 = request.form.get("subject_1", "").strip() or "Ken Research Outreach"
    if template_mode == "kensight_newsletter":
        newsletter_template = request.form.get("newsletter_template", "overview").strip() or "overview"
        if newsletter_template == "automotive_pov":
            body_1 = render_kensight_pov_newsletter(request.form, "cid")
        else:
            body_1 = render_kensight_newsletter(request.form, "cid")
    else:
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

@app.route("/assets/newsletter/<path:filename>", methods=["GET"])
def newsletter_asset(filename):
    if filename not in NEWSLETTER_ASSET_FILES:
        return jsonify({"error": "Asset not found"}), 404
    return send_from_directory(NEWSLETTER_ASSETS_DIR, filename)


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
            {"email": d["recipient"], "first_name": d.get("first_name", ""), "company": d.get("company", ""), "designation": d.get("designation", "")}
            for d in progress.get("send_details", [])
            if current_step not in d.get("steps_completed", [])
            and d.get("status") not in ("failed", "skipped")
            and not d.get("replied")
        ]
        if not pending_recipients:
            pending_recipients = [
                {"email": d["recipient"], "first_name": d.get("first_name", ""), "company": d.get("company", ""), "designation": d.get("designation", "")}
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


@app.route("/retry/<campaign_id>", methods=["POST"])
def retry_campaign(campaign_id):
    try:
        progress = _load_progress(campaign_id)
        brief = _load_brief(campaign_id)

        if not progress or not brief:
            flash(f"Campaign '{campaign_id}' not found.", "error")
            return redirect(url_for("dashboard"))

        all_sequences = brief.get("email_sequences", [])
        original_send_details = progress.get("send_details", [])

        if not original_send_details:
            flash(f"No recipients to retry for '{campaign_id}'.", "error")
            return redirect(url_for("dashboard"))

        retry_recipients = [
            {"email": r["recipient"], "first_name": r.get("first_name", ""), "company": r.get("company", ""), "designation": r.get("designation", "")}
            for r in original_send_details
        ]

        account_num = brief.get("account_number", "1")
        tracker_url = get_tracker_url()

        progress["campaign_status"] = "active"
        progress["current_step"] = 1
        progress["next_step_send_at"] = None
        progress["last_update"] = datetime.now().isoformat()
        progress["send_details"] = [
            {
                "recipient": r["recipient"],
                "first_name": r.get("first_name", ""),
                "company": r.get("company", ""),
                "designation": r.get("designation", ""),
                "step": 0,
                "steps_completed": [],
                "status": "pending",
                "sent_at": None,
                "retry_count": 0,
            }
            for r in original_send_details
        ]
        _save_progress(campaign_id, progress)

        remaining = all_sequences or [{"step": 1, "delay_days": 0, "subject": "", "body": ""}]

        threading.Thread(
            target=bulk_send_worker,
            args=(campaign_id, account_num, retry_recipients, remaining, tracker_url),
            daemon=True,
        ).start()

        flash(f"'{campaign_id}': Retrying from Step 1 with all {len(retry_recipients)} recipients.", "success")

    except Exception as e:
        flash(f"Error retrying campaign: {str(e)}", "error")
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


@app.route("/campaign/<campaign_id>/add-recipients", methods=["POST"])
def add_recipients(campaign_id):
    """Add more POCs to an existing campaign (running or not) via Excel/CSV upload.
    New recipients always start at Step 1 of the campaign's own sequence, on their
    own timeline — independent of whatever step the original batch is currently on."""
    brief = _load_brief(campaign_id)
    progress = _load_progress(campaign_id)
    if not brief:
        flash(f"Campaign '{campaign_id}' not found.", "error")
        return redirect(url_for("dashboard"))

    file = request.files.get("recipients_file")
    if not file or not file.filename:
        flash("Upload an Excel/CSV file with new recipients.", "error")
        return redirect(url_for("campaign_detail", campaign_id=campaign_id))

    try:
        new_recipients = parse_recipients_excel(file)
    except Exception as e:
        flash(f"Could not read the uploaded file: {e}", "error")
        return redirect(url_for("campaign_detail", campaign_id=campaign_id))

    if not new_recipients:
        flash("No valid rows found. Make sure the file has an 'Email' column header.", "error")
        return redirect(url_for("campaign_detail", campaign_id=campaign_id))

    existing_emails = {d["recipient"] for d in progress.get("send_details", [])}
    fresh = [r for r in new_recipients if r["email"] not in existing_emails]
    skipped_dupes = len(new_recipients) - len(fresh)

    if not fresh:
        flash(f"All {len(new_recipients)} recipient(s) in this file are already in the campaign.", "error")
        return redirect(url_for("campaign_detail", campaign_id=campaign_id))

    progress.setdefault("send_details", []).extend([
        {
            "recipient": r["email"],
            "first_name": r.get("first_name", ""),
            "company": r.get("company", ""),
            "designation": r.get("designation", ""),
            "step": 0,
            "steps_completed": [],
            "status": "pending",
            "sent_at": None,
            "retry_count": 0,
        }
        for r in fresh
    ])
    progress["total_recipients"] = progress.get("total_recipients", 0) + len(fresh)
    progress["pending"] = progress.get("pending", 0) + len(fresh)
    progress["last_update"] = datetime.now().isoformat()
    _save_progress(campaign_id, progress)

    account_num = brief.get("account_number", "1")
    sequences = brief.get("email_sequences", [])
    tracker_url = get_tracker_url()
    batch_lock_key = f"{campaign_id}:addon:{int(datetime.now().timestamp())}"

    threading.Thread(
        target=bulk_send_worker,
        args=(campaign_id, account_num, fresh, sequences, tracker_url, batch_lock_key),
        daemon=True,
    ).start()

    msg = f"Added {len(fresh)} new recipient(s) to '{campaign_id}' — starting Step 1 now."
    if skipped_dupes:
        msg += f" ({skipped_dupes} already in this campaign, skipped.)"
    flash(msg, "success")
    return redirect(url_for("campaign_detail", campaign_id=campaign_id))


@app.route("/pause-all", methods=["POST"])
def pause_all():
    try:
        all_campaigns = query_db("SELECT campaign_id, progress FROM campaigns")
        paused = 0
        for row in all_campaigns:
            prog = row["progress"] if isinstance(row["progress"], dict) else json.loads(row["progress"])
            if prog.get("campaign_status") not in ("completed", "paused"):
                prog["campaign_status"] = "paused"
                prog["last_update"] = datetime.now().isoformat()
                _save_progress(row["campaign_id"], prog)
                paused += 1
        flash(f"All campaigns paused ({paused} stopped). Running threads will halt before their next send.", "success")
    except Exception as e:
        flash(f"Error pausing campaigns: {e}", "error")
    return redirect(url_for("dashboard"))


@app.route("/resume-all", methods=["POST"])
def resume_all():
    try:
        all_campaigns = query_db("SELECT campaign_id, brief, progress FROM campaigns")
        resumed = 0
        for row in all_campaigns:
            brief = row["brief"] if isinstance(row["brief"], dict) else json.loads(row["brief"])
            prog = row["progress"] if isinstance(row["progress"], dict) else json.loads(row["progress"])
            cid = row["campaign_id"]
            if prog.get("campaign_status") != "paused":
                continue

            # Restore to waiting or active based on whether a next_step time exists
            next_send_at = prog.get("next_step_send_at")
            if next_send_at:
                prog["campaign_status"] = "waiting"
            else:
                prog["campaign_status"] = "active"
            prog["last_update"] = datetime.now().isoformat()
            _save_progress(cid, prog)

            # Restart worker thread
            current_step = prog.get("current_step", 1)
            all_sequences = brief.get("email_sequences", [])
            pending = [
                {"email": d["recipient"], "first_name": d.get("first_name", ""), "company": d.get("company", ""), "designation": d.get("designation", "")}
                for d in prog.get("send_details", [])
                if current_step not in d.get("steps_completed", [])
                and d.get("status") not in ("failed", "skipped")
                and not d.get("replied")
            ]
            if not pending:
                continue
            remaining_seqs = [s for s in all_sequences if s["step"] >= current_step] or all_sequences
            account_num = brief.get("account_number", "1")
            tracker_url = get_tracker_url()
            threading.Thread(
                target=bulk_send_worker,
                args=(cid, account_num, pending, remaining_seqs, tracker_url),
                daemon=True,
            ).start()
            resumed += 1

        flash(f"All paused campaigns resumed ({resumed} restarted).", "success")
    except Exception as e:
        flash(f"Error resuming campaigns: {e}", "error")
    return redirect(url_for("dashboard"))


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
            if campaign_status in ("completed", "paused"):
                continue

            current_step = progress.get("current_step", 1)
            all_sequences = brief.get("email_sequences", [])

            pending = [
                {"email": d["recipient"], "first_name": d.get("first_name", ""), "company": d.get("company", ""), "designation": d.get("designation", "")}
                for d in progress.get("send_details", [])
                if current_step not in d.get("steps_completed", [])
                and d.get("status") not in ("failed", "skipped")
                and not d.get("replied")
            ]
            if not pending:
                pending = [
                    {"email": d["recipient"], "first_name": d.get("first_name", ""), "company": d.get("company", ""), "designation": d.get("designation", "")}
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


def bounce_checker_worker():
    """Background thread: polls sender inboxes every 60s for NDR/bounce notifications.

    Graph API's 202 response only means "accepted for relay" — it is not proof of
    delivery. A hard bounce (bad mailbox, domain rejects address, etc.) arrives later
    as a separate Mail Delivery System email in the same inbox, completely invisible
    to the original send call. Without this check, those recipients stay marked
    "sent"/Delivered forever even though the mail never reached anyone — which is
    exactly what was driving false "Delivered" counts and repeat bounces hurting
    sender reputation.

    For each NDR found, the bounced recipient's address is matched by substring
    against this campaign's own 'sent' recipients (NDR bodies always quote the
    original address verbatim), then flipped to 'failed' so it shows under
    Undelivered and is excluded from any further follow-up steps.
    """
    import time
    from send_email import read_bounces

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

                sent_recipients = {
                    d["recipient"]: d
                    for d in progress.get("send_details", [])
                    if d.get("status") == "sent"
                }
                if not sent_recipients:
                    continue

                bounces = read_bounces(account_num, since_dt)
                if not bounces:
                    continue

                updated = False
                for b in bounces:
                    body_l = b["body_text"].lower()
                    matched = [email for email in list(sent_recipients.keys()) if email in body_l]
                    for email in matched:
                        detail = sent_recipients.pop(email)
                        detail["status"] = "failed"
                        detail["fail_reason"] = f"Bounced: {b['subject'][:150]}"
                        progress["sent"] = max(0, progress.get("sent", 0) - 1)
                        progress["failed"] = progress.get("failed", 0) + 1
                        updated = True
                        print(f"[BOUNCE] {campaign_id}: {email} bounced — {b['subject'][:80]}")

                if updated:
                    progress["last_update"] = datetime.now().isoformat()
                    _save_progress(campaign_id, progress)

            except Exception as e:
                print(f"[BOUNCE CHECK ERROR] {row.get('campaign_id', '?')}: {e}")


# Run on startup regardless of whether launched via Python or gunicorn
init_db()
auto_resume_pending_campaigns()
threading.Thread(target=reply_checker_worker, daemon=True).start()
threading.Thread(target=bounce_checker_worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    print(f"[OK] Ken Research Email Campaign App running on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
