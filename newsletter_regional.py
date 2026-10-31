"""Email-safe Regional Market Outlook newsletter renderer."""

from html import escape
from io import BytesIO

from PIL import Image


DEFAULT_URL = "https://www.kenresearch.com"
CANVAS_WIDTH = 600
REGIONAL_SLOTS = ("hero", "insights", "report")
SLOT_SIZES = {
    "hero": (572, 504),
    "insights": (340, 660),
    "report": (172, 224),
}
IMAGE_FILES = {
    "hero": "regional-hero.jpg",
    "insights": "regional-insights.jpg",
    "report": "regional-report-cover.jpg",
}

NAVY = "#13203a"
RED = "#ed1c24"
PEACH = "#fdf7f1"
GREY = "#4b5563"
LIGHT_GREY = "#6b7280"
RULE = "#e1e5e8"


def _v(form, name, default=""):
    return (form.get(name, default) or "").strip()


def _text(value):
    return escape(value, quote=True).replace("\n", "<br>")


def _url(value):
    value = (value or "").strip()
    if value.lower().startswith(("http://", "https://", "mailto:")):
        return escape(value, quote=True)
    return DEFAULT_URL


def regional_content(form):
    content = {
        "section_label": _v(form, "reg_section_label", "Regional Market Outlook"),
        "issue_label": _v(form, "reg_issue_label", "Oct 2026 | Issue 01"),
        "region": _v(form, "reg_region", "India"),
        "hero_title": _v(form, "reg_hero_title"),
        "hero_body": _v(form, "reg_hero_body"),
        "hero_cta_text": _v(form, "reg_hero_cta_text", "Read the Full Perspective"),
        "hero_cta_url": _v(form, "reg_hero_cta_url", DEFAULT_URL),
        "insights_heading": _v(form, "reg_insights_heading", "Key Insights"),
        "report_label": _v(form, "reg_report_label", "Final File Report"),
        "report_title": _v(form, "reg_report_title"),
        "report_body": _v(form, "reg_report_body"),
        "report_cta_text": _v(form, "reg_report_cta_text", "View Report"),
        "report_cta_url": _v(form, "reg_report_cta_url", DEFAULT_URL),
        "contact_url": _v(form, "reg_contact_url", "https://www.kenresearch.com/contact-us"),
        "unsubscribe_url": _v(form, "reg_unsubscribe_url", DEFAULT_URL),
        "linkedin_url": _v(form, "reg_social_linkedin", "https://www.linkedin.com/company/ken-research"),
        "x_url": _v(form, "reg_social_x", "https://x.com/kenresearch"),
        "youtube_url": _v(form, "reg_social_youtube", "https://www.youtube.com/@kenresearch"),
    }
    defaults = (
        "Expanding insurance-led demand",
        "Accelerating digital health adoption",
        "Growing Tier 2/3 capacity needs",
        "Rising specialty care investment",
    )
    content["indicators"] = [
        _v(form, f"reg_indicator{number}", defaults[number - 1]) for number in range(1, 5)
    ]
    content["insights"] = [
        {
            "title": _v(form, f"reg_insight{number}_title"),
            "body": _v(form, f"reg_insight{number}_body"),
            "url": _v(form, f"reg_insight{number}_url", DEFAULT_URL),
        }
        for number in range(1, 4)
    ]
    return content


def validate_regional_content(content):
    problems = []
    if not content["hero_title"]:
        problems.append("Hero headline is required.")
    if not content["hero_body"]:
        problems.append("Hero summary is required.")
    for number, indicator in enumerate(content["indicators"], start=1):
        if not indicator:
            problems.append(f"Market indicator {number} is required.")
    for number, insight in enumerate(content["insights"], start=1):
        if not insight["title"]:
            problems.append(f"Insight {number} title is required.")
        if not insight["body"]:
            problems.append(f"Insight {number} summary is required.")
    if not content["report_title"]:
        problems.append("Report title is required.")
    if not content["report_body"]:
        problems.append("Report summary is required.")
    return problems


def prepare_regional_image(slot, raw, max_bytes=12 * 1024 * 1024):
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
    source.save(output, "JPEG", quality=88, optimize=True)
    return output.getvalue()


def _button(text, url, width=216, height=30, font_size=11):
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="{width}"><tr>'
        f'<td width="{width}" height="{height}" align="center" bgcolor="{RED}" '
        f'style="background:{RED};border-radius:2px;mso-padding-alt:0;">'
        f'<a href="{_url(url)}" target="_blank" style="display:block;width:{width}px;line-height:{height}px;'
        f'font-family:Arial,Helvetica,sans-serif;font-size:{font_size}px;font-weight:700;color:#ffffff;'
        f'text-decoration:none;">{_text(text)}&nbsp;&nbsp;&#8594;</a></td></tr></table>'
    )


def render_regional_newsletter(form, asset_base_url="", image_src=None):
    content = regional_content(form)
    image_src = image_src or {}

    def asset(filename):
        base = (asset_base_url or "").strip()
        if base.lower() == "cid":
            return f"cid:{filename}"
        return f"{base.rstrip('/')}/assets/newsletter/{filename}"

    logo = asset("regional-ken-research-logo.png")
    report_icon = asset("industry-report-icon.png")
    tagline = "GLOBAL STRATEGIC CONSULTING &amp; MARKET INTELLIGENCE"
    indicator_cells = []
    for number, indicator in enumerate(content["indicators"], start=1):
        border = "" if number == 4 else f"border-right:1px solid {RULE};"
        indicator_cells.append(f"""
          <td width="142" align="center" valign="top" style="width:142px;padding:12px 8px 10px;{border}">
            <img src="{asset(f'regional-indicator-{number}.png')}" width="34" height="34" alt="" style="display:block;width:34px;height:34px;border:0;">
            <div style="padding-top:6px;font-family:Arial,Helvetica,sans-serif;font-size:9px;line-height:11px;color:{NAVY};">{_text(indicator)}</div>
          </td>""")

    insight_rows = []
    for number, insight in enumerate(content["insights"], start=1):
        border = "" if number == 3 else f"border-bottom:1px solid {RULE};"
        insight_rows.append(f"""
          <tr><td style="padding:9px 0;{border}">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="344"><tr>
              <td width="40" valign="top" style="width:40px;font-family:Georgia,'Times New Roman',serif;font-size:18px;line-height:20px;color:#9ca3af;">0{number}</td>
              <td width="304" valign="top" style="width:304px;">
                <a href="{_url(insight['url'])}" target="_blank" style="font-family:Georgia,'Times New Roman',serif;font-size:13px;line-height:15px;font-weight:700;color:{NAVY};text-decoration:none;">{_text(insight['title'])}</a>
                <div style="padding-top:3px;font-family:Arial,Helvetica,sans-serif;font-size:9px;line-height:12px;color:{GREY};">{_text(insight['body'])}</div>
              </td>
            </tr></table>
          </td></tr>""")

    def social(filename, url, alt):
        return (
            f'<td style="padding-left:7px;"><a href="{_url(url)}" target="_blank">'
            f'<img src="{asset(filename)}" width="20" height="20" alt="{alt}" '
            f'style="display:block;width:20px;height:20px;border:0;"></a></td>'
        )

    footer_style = f"font-family:Arial,Helvetica,sans-serif;font-size:8px;color:{LIGHT_GREY};text-decoration:none;"
    separator = '<span style="color:#9ca3af;">&nbsp;&nbsp;|&nbsp;&nbsp;</span>'

    return f"""
<div style="display:none;font-size:1px;color:#f4f4f4;line-height:1px;max-height:0;opacity:0;overflow:hidden;">{_text(content['hero_title'])}</div>
<style>
  @media only screen and (max-width:600px) {{
    .reg-wrap {{ width:100% !important; }}
    .reg-stack {{ display:block !important;width:100% !important;box-sizing:border-box; }}
    .reg-img {{ width:100% !important;height:auto !important; }}
  }}
</style>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#f4f4f4" style="width:100%;background:#f4f4f4;margin:0;padding:0;">
  <tr><td align="center" style="padding:0 4px;">
    <table role="presentation" class="reg-wrap" cellpadding="0" cellspacing="0" border="0" width="600" bgcolor="#ffffff" style="width:600px;max-width:600px;background:#ffffff;border:1px solid #edf0f2;">
      <tr><td style="padding:14px 16px 8px;border-bottom:1px solid {RULE};">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
          <td width="2" bgcolor="{RED}" style="width:2px;background:{RED};font-size:1px;">&nbsp;</td>
          <td valign="bottom" style="padding-left:14px;"><a href="{DEFAULT_URL}" target="_blank"><img src="{logo}" width="200" height="32" alt="Ken Research" style="display:block;width:200px;height:32px;border:0;"></a><div style="padding-top:2px;font-family:Arial,sans-serif;font-size:7px;line-height:9px;letter-spacing:.35px;color:{LIGHT_GREY};">{tagline}</div></td>
          <td align="right" valign="bottom" style="font-family:Arial,sans-serif;"><div style="font-size:11px;line-height:14px;font-weight:700;text-transform:uppercase;color:{NAVY};">{_text(content['section_label'])}</div><div style="font-size:9px;line-height:12px;text-transform:uppercase;color:{LIGHT_GREY};">{_text(content['issue_label'])}</div></td>
        </tr></table>
      </td></tr>

      <tr><td style="padding:0 16px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="568" bgcolor="{PEACH}" style="width:568px;background:{PEACH};border-top:2px solid {RED};"><tr>
          <td class="reg-stack" width="282" height="252" valign="top" style="width:282px;height:252px;padding:12px 12px 10px 17px;box-sizing:border-box;">
            <div style="font-family:Arial,sans-serif;font-size:9px;line-height:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:{RED};">Regional Focus: {_text(content['region'])}</div>
            <div style="padding:5px 0;font-family:Georgia,'Times New Roman',serif;font-size:24px;line-height:25px;font-weight:700;color:{NAVY};">{_text(content['hero_title'])}</div>
            <div style="padding-bottom:9px;font-family:Arial,sans-serif;font-size:10px;line-height:14px;color:{GREY};">{_text(content['hero_body'])}</div>
            {_button(content['hero_cta_text'], content['hero_cta_url'])}
          </td>
          <td class="reg-stack" width="286" height="252" valign="top"><img class="reg-img" src="{image_src.get('hero', '')}" width="286" height="252" alt="" style="display:block;width:286px;height:252px;object-fit:cover;border:0;"></td>
        </tr></table>
      </td></tr>

      <tr><td style="padding:0 16px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="568" style="width:568px;border-bottom:1px solid {RULE};"><tr>{''.join(indicator_cells)}</tr></table></td></tr>

      <tr><td style="padding:12px 32px 0;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="536"><tr><td nowrap style="padding-right:10px;font-family:Arial,sans-serif;font-size:14px;line-height:18px;font-weight:700;text-transform:uppercase;color:{NAVY};">{_text(content['insights_heading'])}</td><td width="100%"><div style="border-top:2px solid {RED};font-size:0;line-height:0;">&nbsp;</div></td></tr></table></td></tr>
      <tr><td style="padding:4px 32px 10px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="536"><tr>
        <td class="reg-stack" width="170" height="330" valign="top"><img class="reg-img" src="{image_src.get('insights', '')}" width="170" height="330" alt="" style="display:block;width:170px;height:330px;object-fit:cover;border:0;"></td>
        <td class="reg-stack" width="344" valign="top" style="width:344px;padding-left:22px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="344">{''.join(insight_rows)}</table></td>
      </tr></table></td></tr>

      <tr><td style="padding:0 32px 10px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="536" bgcolor="{PEACH}" style="width:536px;background:{PEACH};"><tr>
        <td width="48" valign="top" style="width:48px;padding:12px 0 0 8px;"><img src="{report_icon}" width="26" height="30" alt="" style="display:block;border:0;"></td>
        <td width="366" valign="top" style="width:366px;padding:12px 10px 10px 0;"><div style="font-family:Arial,sans-serif;font-size:9px;line-height:12px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:{RED};">{_text(content['report_label'])}</div><div style="padding-top:2px;font-family:Georgia,'Times New Roman',serif;font-size:15px;line-height:17px;font-weight:700;color:{NAVY};">{_text(content['report_title'])}</div><div style="padding:3px 0 9px;font-family:Arial,sans-serif;font-size:9px;line-height:12px;color:{GREY};">{_text(content['report_body'])}</div>{_button(content['report_cta_text'], content['report_cta_url'], 142, 24, 9)}</td>
        <td width="102" align="center" valign="middle"><img src="{image_src.get('report', '')}" width="86" height="112" alt="Report cover" style="display:block;width:86px;height:112px;object-fit:cover;border:0;"></td>
      </tr></table></td></tr>

      <tr><td style="padding:0 32px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="536" height="40" style="width:536px;border-top:1px solid {RULE};"><tr><td valign="middle"><img src="{logo}" width="140" height="23" alt="Ken Research" style="display:block;border:0;"><div style="font-family:Arial,sans-serif;font-size:6px;line-height:7px;color:{LIGHT_GREY};">{tagline}</div></td><td align="right"><table role="presentation" cellpadding="0" cellspacing="0" border="0" align="right"><tr>{social('mailmodo-linkedin.png', content['linkedin_url'], 'LinkedIn')}{social('mailmodo-twitter.png', content['x_url'], 'X')}{social('mailmodo-youtube.png', content['youtube_url'], 'YouTube')}</tr></table></td></tr></table></td></tr>
      <tr><td height="16" align="center" valign="top" style="padding:0 32px;"><a href="{_url(content['contact_url'])}" target="_blank" style="{footer_style}">Contact Us</a>{separator}<a href="{_url(content['unsubscribe_url'])}" target="_blank" style="{footer_style}">Unsubscribe</a></td></tr>
    </table>
  </td></tr>
</table>"""
