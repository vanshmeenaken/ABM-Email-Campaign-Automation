"""Email-safe Leader's Perspective newsletter renderer."""

from html import escape
from io import BytesIO
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from PIL import Image


DEFAULT_URL = "https://www.kenresearch.com"
CANVAS_WIDTH = 600
LEADER_SLOTS = ("hero", "portrait", "reading", "report")
REQUIRED_UPLOAD_SLOTS = ("hero", "reading", "report")
SLOT_SIZES = {
    "hero": (600, 520),
    "portrait": (360, 360),
    "reading": (400, 300),
    "report": (240, 320),
}
IMAGE_FILES = {
    "hero": "leader-perspective-hero.jpg",
    "portrait": "leader-perspective-portrait.jpg",
    "reading": "leader-perspective-reading.jpg",
    "report": "leader-perspective-report.jpg",
}
DEFAULT_PORTRAIT_FILE = "leaders-namit-goel.jpg"

NAVY = "#102448"
RED = "#ed1c24"
BLUSH = "#fff5f7"
PALE = "#fff9f9"
GREY = "#52627b"
LIGHT_GREY = "#6b7280"
RULE = "#e5e7eb"


def _v(form, name, default=""):
    return (form.get(name, default) or "").strip()


def _text(value):
    return escape(value or "", quote=True).replace("\n", "<br>")


def _valid_url(value):
    value = (value or "").strip()
    parsed = urlparse(value)
    return value if parsed.scheme.lower() in {"http", "https"} and parsed.netloc else ""


def _url(value):
    return escape(_valid_url(value), quote=True)


def _with_utms(value, content):
    value = _valid_url(value)
    if not value:
        return ""
    parsed = urlparse(value)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in ("utm_source", "utm_medium", "utm_campaign"):
        if content.get(key) and not query.get(key):
            query[key] = content[key]
    return urlunparse(parsed._replace(query=urlencode(query)))


def _is_generic_homepage(value):
    parsed = urlparse(_valid_url(value))
    return (
        parsed.netloc.lower() in {"kenresearch.com", "www.kenresearch.com"}
        and parsed.path.rstrip("/") == ""
    )


def leader_content(form):
    return {
        "section_label": _v(form, "lead_section_label", "Leader's Perspective"),
        "industry_label": _v(form, "lead_industry_label", "BFSI"),
        "region_label": _v(form, "lead_region_label", "Southeast Asia"),
        "issue_label": _v(form, "lead_issue_label", "October 2026 | Issue 01"),
        "brand_url": _v(form, "lead_brand_url", DEFAULT_URL),
        "utm_source": _v(form, "lead_utm_source", "newsletter"),
        "utm_medium": _v(form, "lead_utm_medium", "email"),
        "utm_campaign": _v(form, "lead_utm_campaign", "leaders_perspective"),
        "hero_kicker": _v(form, "lead_hero_kicker", "Vietnam | Digital Financial Services"),
        "hero_title": _v(form, "lead_hero_title"),
        "hero_body": _v(form, "lead_hero_body"),
        "hero_cta_text": _v(form, "lead_hero_cta_text", "Read the Full Article"),
        "hero_cta_url": _v(form, "lead_hero_cta_url"),
        "leader_label": _v(form, "lead_leader_label", "From the Leader"),
        "leader_name": _v(form, "lead_leader_name", "Namit Goel"),
        "leader_role": _v(form, "lead_leader_role", "Co-Founder & Director, Ken Research"),
        "leader_quote": _v(form, "lead_leader_quote"),
        "reading_label": _v(form, "lead_reading_label", "Further Reading"),
        "reading_meta": _v(form, "lead_reading_meta", "Southeast Asia | SME Lending | September 2026"),
        "reading_title": _v(form, "lead_reading_title"),
        "reading_body": _v(form, "lead_reading_body"),
        "reading_cta_text": _v(form, "lead_reading_cta_text", "Explore the Regional Benchmarking Research"),
        "reading_cta_url": _v(form, "lead_reading_cta_url"),
        "report_label": _v(form, "lead_report_label", "Featured Market Intelligence"),
        "report_title": _v(form, "lead_report_title"),
        "report_body": _v(form, "lead_report_body"),
        "report_cta_text": _v(form, "lead_report_cta_text", "Explore Vietnam's Wealth Market"),
        "report_cta_url": _v(form, "lead_report_cta_url"),
        "contact_url": _v(form, "lead_contact_url", "https://www.kenresearch.com/contact-us"),
        "unsubscribe_url": _v(form, "lead_unsubscribe_url", DEFAULT_URL),
        "linkedin_url": _v(form, "lead_social_linkedin", "https://www.linkedin.com/company/ken-research"),
        "x_url": _v(form, "lead_social_x", "https://x.com/kenresearch"),
        "youtube_url": _v(form, "lead_social_youtube", "https://www.youtube.com/@kenresearch"),
    }


def resolved_leader_links(content):
    links = {
        "Header logo": content["brand_url"],
        "Hero article": content["hero_cta_url"],
        "Further reading": content["reading_cta_url"],
        "Featured intelligence": content["report_cta_url"],
        "Contact Us": content["contact_url"],
        "LinkedIn": content["linkedin_url"],
        "X": content["x_url"],
        "YouTube": content["youtube_url"],
    }
    return {label: _with_utms(url, content) for label, url in links.items()}


def validate_leader_content(content):
    problems = []
    required_text = {
        "Hero headline": content["hero_title"],
        "Hero summary": content["hero_body"],
        "Leader name": content["leader_name"],
        "Leader role": content["leader_role"],
        "Leader quote": content["leader_quote"],
        "Further reading headline": content["reading_title"],
        "Further reading summary": content["reading_body"],
        "Featured intelligence headline": content["report_title"],
        "Featured intelligence summary": content["report_body"],
    }
    for label, value in required_text.items():
        if not value:
            problems.append(f"{label} is required.")

    required_links = {
        "Header logo link": content["brand_url"],
        "Hero article link": content["hero_cta_url"],
        "Further reading link": content["reading_cta_url"],
        "Featured intelligence link": content["report_cta_url"],
        "Contact Us link": content["contact_url"],
        "LinkedIn link": content["linkedin_url"],
        "X link": content["x_url"],
        "YouTube link": content["youtube_url"],
    }
    for label, value in required_links.items():
        if not _valid_url(value):
            problems.append(f"{label} must be a complete http:// or https:// URL.")
    for label, value in (
        ("Hero article link", content["hero_cta_url"]),
        ("Further reading link", content["reading_cta_url"]),
        ("Featured intelligence link", content["report_cta_url"]),
    ):
        if _is_generic_homepage(value):
            problems.append(f"{label} cannot use the generic Ken Research homepage.")
    return problems


def prepare_leader_image(slot, raw, max_bytes=12 * 1024 * 1024):
    if slot not in SLOT_SIZES:
        raise ValueError(f"Unknown image slot: {slot}")
    if not raw:
        raise ValueError("The uploaded image is empty.")
    if len(raw) > max_bytes:
        raise ValueError("The uploaded image is larger than 12 MB.")
    try:
        source = Image.open(BytesIO(raw))
        if source.format not in {"PNG", "JPEG", "WEBP", "AVIF"}:
            raise ValueError("The upload must be a PNG, JPEG, WebP, or AVIF image.")
        source.load()
        if source.width < 200 or source.height < 120:
            raise ValueError("The uploaded image is too small (minimum 200 x 120 pixels).")
        if source.width > 8192 or source.height > 8192:
            raise ValueError("The uploaded image dimensions are too large.")
        target_width, target_height = SLOT_SIZES[slot]
        source = source.convert("RGB")
        target_ratio = target_width / target_height
        if source.width / source.height > target_ratio:
            new_width = int(source.height * target_ratio)
            left = (source.width - new_width) // 2
            source = source.crop((left, 0, left + new_width, source.height))
        else:
            new_height = int(source.width / target_ratio)
            top = (source.height - new_height) // 2
            source = source.crop((0, top, source.width, top + new_height))
        source = source.resize((target_width, target_height), Image.Resampling.LANCZOS)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The upload is not a valid PNG, JPEG, WebP, or AVIF image.") from exc
    output = BytesIO()
    source.save(output, "JPEG", quality=90, optimize=True)
    return output.getvalue()


def _section_rule(label):
    return f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
      <td width="30" valign="middle"><div style="border-top:3px solid {RED};font-size:0;line-height:0;">&nbsp;</div></td>
      <td style="padding-left:12px;font-family:Georgia,'Times New Roman',serif;font-size:10px;line-height:13px;font-weight:700;letter-spacing:2.2px;text-transform:uppercase;color:{NAVY};">{_text(label)}</td>
    </tr></table>'''


def _text_cta(text, url):
    return (
        f'<a href="{_url(url)}" target="_blank" style="font-family:Georgia,\'Times New Roman\',serif;'
        f'font-size:11px;line-height:15px;font-weight:700;color:{RED};text-decoration:none;">'
        f'{_text(text)}&nbsp;&nbsp;&#8594;</a>'
    )


def _wrapped_line_count(value, line_units):
    """Estimate email-client wrapping without relying on unsupported scripting."""
    lines = 0
    current = 0
    for paragraph in (value or "").splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines += 1
            continue
        for word in words:
            word_units = len(word)
            if current and current + 1 + word_units > line_units:
                lines += 1
                current = word_units
            else:
                current = current + (1 if current else 0) + word_units
        lines += 1
        current = 0
    return max(1, lines)


def _hero_height(content):
    """Size the photo to the submitted copy while keeping email-safe dimensions."""
    title_lines = _wrapped_line_count(content["hero_title"], 22)
    body_lines = _wrapped_line_count(content["hero_body"], 47)
    # The fixed allowance covers the kicker, title/body spacing and CTA. Do not
    # add decorative bottom space: the image and CTA must finish together.
    estimated = 57 + (title_lines * 25) + (body_lines * 15)
    return max(190, min(360, estimated))


def render_leader_newsletter(form, asset_base_url="", image_src=None):
    content = leader_content(form)
    links = resolved_leader_links(content)
    image_src = image_src or {}
    hero_height = _hero_height(content)

    def asset(filename):
        base = (asset_base_url or "").strip()
        if base.lower() == "cid":
            return f"cid:{filename}"
        return f"{base.rstrip('/')}/assets/newsletter/{filename}"

    logo = asset("ken-research-logo-color.png")
    portrait = image_src.get("portrait") or asset(DEFAULT_PORTRAIT_FILE)

    def social(filename, url, alt):
        return (
            f'<td style="padding-left:7px;"><a href="{_url(url)}" target="_blank">'
            f'<img src="{asset(filename)}" width="18" height="18" alt="{alt}" '
            f'style="display:block;width:18px;height:18px;border:0;"></a></td>'
        )

    footer_style = f"font-family:Arial,Helvetica,sans-serif;font-size:8px;color:{LIGHT_GREY};text-decoration:none;"
    separator = '<span style="color:#b7bec8;">&nbsp;&nbsp;|&nbsp;&nbsp;</span>'

    return f'''<div style="display:none;font-size:1px;color:#f4f4f4;line-height:1px;max-height:0;opacity:0;overflow:hidden;">{_text(content['hero_title'])}</div>
<style>
  @media only screen and (max-width:600px) {{
    .lead-wrap {{ width:100% !important; }}
    .lead-stack {{ display:block !important;width:100% !important;box-sizing:border-box; }}
    .lead-img {{ width:100% !important;height:auto !important; }}
  }}
</style>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#f4f4f4" style="width:100%;background:#f4f4f4;margin:0;padding:0;">
  <tr><td align="center" style="padding:0 4px;">
    <table role="presentation" class="lead-wrap" cellpadding="0" cellspacing="0" border="0" width="600" bgcolor="#ffffff" style="width:600px;max-width:600px;background:#ffffff;border:1px solid #edf0f2;">
      <tr><td style="padding:15px 18px 10px;border-bottom:3px solid {RED};">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
          <td valign="middle"><a href="{_url(links['Header logo'])}" target="_blank"><img src="{logo}" width="200" height="24" alt="Ken Research" style="display:block;width:200px;height:24px;border:0;"></a><div style="padding-top:2px;font-family:Arial,sans-serif;font-size:7px;line-height:9px;color:{LIGHT_GREY};">Global Strategic Consulting &amp; Market Intelligence</div></td>
          <td align="right" valign="middle"><div style="font-family:Georgia,'Times New Roman',serif;font-size:10px;line-height:13px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;color:{RED};">{_text(content['section_label'])}</div><div style="padding-top:3px;font-family:Arial,sans-serif;font-size:8px;line-height:11px;text-transform:uppercase;color:{NAVY};">{_text(content['industry_label'])}&nbsp;&nbsp;|&nbsp;&nbsp;{_text(content['region_label'])}<br>{_text(content['issue_label'])}</div></td>
        </tr></table>
      </td></tr>

      <tr><td><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" style="width:600px;table-layout:fixed;"><tr>
        <td class="lead-stack" width="330" valign="top" style="width:330px;padding:19px 18px 0 22px;">
          <div style="font-family:Georgia,'Times New Roman',serif;font-size:8px;line-height:11px;letter-spacing:1.3px;text-transform:uppercase;color:{NAVY};">{_text(content['hero_kicker'])}</div>
          <div style="padding:9px 0 11px;font-family:Georgia,'Times New Roman',serif;font-size:24px;line-height:25px;font-weight:700;color:{NAVY};">{_text(content['hero_title'])}</div>
          <div style="padding-bottom:17px;font-family:Arial,Helvetica,sans-serif;font-size:10.5px;line-height:15px;color:{GREY};">{_text(content['hero_body'])}</div>
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="248"><tr><td align="center" height="32" bgcolor="{RED}" style="height:32px;background:{RED};border-radius:2px;"><a href="{_url(links['Hero article'])}" target="_blank" style="display:block;line-height:32px;mso-line-height-rule:exactly;font-family:Georgia,'Times New Roman',serif;font-size:12px;font-weight:700;color:#ffffff;text-decoration:none;">{_text(content['hero_cta_text'])}&nbsp;&nbsp;&#8594;</a></td></tr></table>
        </td>
        <td class="lead-stack" width="270" valign="top" style="width:270px;padding:0;"><img class="lead-img" src="{image_src.get('hero', '')}" width="270" height="{hero_height}" alt="Mobile payments in Vietnam" style="display:block;width:270px;height:{hero_height}px;object-fit:cover;border:0;outline:none;text-decoration:none;"></td>
      </tr></table></td></tr>

      <tr><td bgcolor="{BLUSH}" style="padding:12px 22px 13px;background:{BLUSH};"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
        <td class="lead-stack" width="180" align="center" valign="middle" style="width:180px;"><img src="{portrait}" width="150" height="150" alt="{_text(content['leader_name'])}" style="display:block;width:150px;height:150px;object-fit:cover;border-radius:75px;border:0;"></td>
        <td class="lead-stack" width="370" valign="middle" style="width:370px;padding-left:18px;">
          <div style="font-family:Georgia,'Times New Roman',serif;font-size:9px;line-height:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:{RED};">{_text(content['leader_label'])}</div>
          <div style="padding-top:5px;font-family:Georgia,'Times New Roman',serif;font-size:23px;line-height:25px;font-weight:700;color:{NAVY};">{_text(content['leader_name'])}</div>
          <div style="padding-top:3px;font-family:Arial,sans-serif;font-size:10.5px;line-height:14px;color:{GREY};">{_text(content['leader_role'])}</div>
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top:10px;"><tr><td width="24" valign="top" style="font-family:Georgia,serif;font-size:34px;line-height:28px;font-weight:700;color:{RED};">&#8220;</td><td style="font-family:Georgia,'Times New Roman',serif;font-size:12.5px;line-height:17px;font-style:italic;color:{NAVY};">{_text(content['leader_quote'])}</td><td width="20" valign="bottom" align="right" style="font-family:Georgia,serif;font-size:30px;line-height:22px;font-weight:700;color:{RED};">&#8221;</td></tr></table>
        </td>
      </tr></table></td></tr>

      <tr><td style="padding:13px 22px 9px;">{_section_rule(content['reading_label'])}</td></tr>
      <tr><td style="padding:0 22px 18px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="556"><tr>
        <td class="lead-stack" width="200" valign="top"><img class="lead-img" src="{image_src.get('reading', '')}" width="200" height="150" alt="" style="display:block;width:200px;height:150px;object-fit:cover;border-radius:3px;border:0;"></td>
        <td class="lead-stack" width="336" valign="top" style="width:336px;padding-left:20px;">
          <div style="font-family:Georgia,'Times New Roman',serif;font-size:7px;line-height:10px;letter-spacing:1px;text-transform:uppercase;color:{GREY};">{_text(content['reading_meta'])}</div>
          <div style="padding-top:6px;font-family:Georgia,'Times New Roman',serif;font-size:17px;line-height:19px;font-weight:700;color:{NAVY};">{_text(content['reading_title'])}</div>
          <div style="padding:8px 0 11px;font-family:Arial,sans-serif;font-size:10px;line-height:14px;color:{GREY};">{_text(content['reading_body'])}</div>
          {_text_cta(content['reading_cta_text'], links['Further reading'])}
        </td>
      </tr></table></td></tr>

      <tr><td style="padding:0 16px 17px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="568" bgcolor="{PALE}" style="width:568px;background:{PALE};border-radius:6px;"><tr><td colspan="2" style="padding:15px 10px 10px;">{_section_rule(content['report_label'])}</td></tr><tr>
        <td width="132" align="center" valign="top" style="width:132px;padding:0 8px 14px;"><img src="{image_src.get('report', '')}" width="112" height="149" alt="Report cover" style="display:block;width:112px;height:149px;object-fit:cover;border:1px solid #e5e7eb;"></td>
        <td width="410" valign="top" style="width:410px;padding:0 16px 14px 4px;">
          <div style="font-family:Georgia,'Times New Roman',serif;font-size:17px;line-height:20px;font-weight:700;color:{NAVY};">{_text(content['report_title'])}</div>
          <div style="padding:9px 0 12px;font-family:Arial,sans-serif;font-size:10px;line-height:14px;color:{GREY};">{_text(content['report_body'])}</div>
          {_text_cta(content['report_cta_text'], links['Featured intelligence'])}
        </td>
      </tr></table></td></tr>

      <tr><td style="padding:0 18px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="564" height="52" style="width:564px;border-top:1px solid {RULE};"><tr>
        <td valign="middle"><img src="{logo}" width="140" height="17" alt="Ken Research" style="display:block;width:140px;height:17px;border:0;"><div style="font-family:Arial,sans-serif;font-size:6px;line-height:8px;color:{LIGHT_GREY};">Global Strategic Consulting &amp; Market Intelligence</div></td>
        <td align="right" valign="middle"><table role="presentation" cellpadding="0" cellspacing="0" border="0" align="right"><tr>{social('mailmodo-linkedin.png', links['LinkedIn'], 'LinkedIn')}{social('mailmodo-twitter.png', links['X'], 'X')}{social('mailmodo-youtube.png', links['YouTube'], 'YouTube')}<td style="padding-left:10px;"><a href="{_url(links['Contact Us'])}" target="_blank" style="{footer_style}">Contact Us</a>{separator}<a href="{_url(content['unsubscribe_url'])}" target="_blank" style="{footer_style}">Unsubscribe</a></td></tr></table></td>
      </tr></table></td></tr>
    </table>
  </td></tr>
</table>'''
