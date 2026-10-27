"""Pixel-matched Industry Intelligence newsletter renderer.

The supplied 608 x 909 reference is treated as a 600 px email canvas. All
important dimensions are expressed explicitly because Outlook ignores many
browser layout rules and otherwise changes the proportions.
"""

from html import escape

DEFAULT_URL = "https://www.kenresearch.com"

IMAGE_FILES = {
    "hero": "ind-hero.jpg",
    "dev1": "ind-dev1.jpg",
    "dev2": "ind-dev2.jpg",
    "dev3": "ind-dev3.jpg",
    "report": "ind-report-cover.jpg",
}

CANVAS_WIDTH = 600
HERO_IMAGE_WIDTH = 286
HERO_IMAGE_HEIGHT = 303
DEVELOPMENT_IMAGE_WIDTH = 184
DEVELOPMENT_IMAGE_HEIGHT = 90
REPORT_WIDTH = 536
REPORT_HEIGHT = 130

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


def industry_content(form):
    """Read operator-entered template fields and apply safe defaults."""
    content = {
        "section_label": _v(form, "ind_section_label", "Industry Intelligence"),
        "issue_label": _v(form, "ind_issue_label", "Oct 2026 | Issue 01"),
        "industry": _v(form, "ind_industry", "Automotive"),
        "hero_kicker": _v(form, "ind_hero_kicker", "Key updates across sectors"),
        "hero_title": _v(form, "ind_hero_title"),
        "hero_body": _v(form, "ind_hero_body"),
        "hero_cta_text": _v(form, "ind_hero_cta_text", "Read the Full Perspective"),
        "hero_cta_url": _v(form, "ind_hero_cta_url", DEFAULT_URL),
        "list_heading": _v(form, "ind_list_heading", "Top Developments in Automotive"),
        "source_note": _v(form, "ind_source_note"),
        "report_label": _v(form, "ind_report_label", "Featured deep-dive report"),
        "report_title": _v(form, "ind_report_title"),
        "report_body": _v(form, "ind_report_body"),
        "report_supporting": _v(
            form,
            "ind_report_supporting",
            "Explore the comprehensive market analysis for deeper context in the industry's competitive landscape.",
        ),
        "report_cta_text": _v(form, "ind_report_cta_text", "Explore the Full Market Report"),
        "report_cta_url": _v(form, "ind_report_cta_url", DEFAULT_URL),
        "contact_url": _v(form, "ind_contact_url", "https://www.kenresearch.com/contact-us"),
        "preferences_url": _v(form, "ind_preferences_url", DEFAULT_URL),
        "unsubscribe_url": _v(form, "ind_unsubscribe_url", DEFAULT_URL),
        "linkedin_url": _v(form, "ind_social_linkedin", "https://www.linkedin.com/company/ken-research"),
        "x_url": _v(form, "ind_social_x", "https://x.com/kenresearch"),
        "youtube_url": _v(form, "ind_social_youtube", "https://www.youtube.com/@kenresearch"),
    }
    content["developments"] = [
        {
            "tag": _v(form, f"ind_dev{number}_tag"),
            "title": _v(form, f"ind_dev{number}_title"),
            "body": _v(form, f"ind_dev{number}_body"),
            "url": _v(form, f"ind_dev{number}_url", DEFAULT_URL),
        }
        for number in (1, 2, 3)
    ]
    return content


def image_specs(content):
    specs = {"hero": (content["hero_title"], content["hero_body"])}
    for number, development in enumerate(content["developments"], start=1):
        specs[f"dev{number}"] = (development["title"], development["body"])
    return specs


def validate_industry_content(content):
    problems = []
    if not content["hero_title"]:
        problems.append("Hero headline is required.")
    if not content["hero_body"]:
        problems.append("Hero summary is required.")
    for number, development in enumerate(content["developments"], start=1):
        if not development["title"]:
            problems.append(f"Development {number} headline is required.")
        if not development["body"]:
            problems.append(f"Development {number} summary is required.")
    return problems


def _button(text, url, width, height, font_size):
    """Fixed-size bulletproof button whose geometry survives Outlook desktop."""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="{width}" '
        f'style="width:{width}px;"><tr>'
        f'<td width="{width}" height="{height}" align="center" valign="middle" bgcolor="{RED}" '
        f'style="width:{width}px;height:{height}px;background-color:{RED};border-radius:2px;'
        f'mso-padding-alt:0;mso-line-height-rule:exactly;">'
        f'<a href="{_url(url)}" target="_blank" style="display:block;width:{width}px;'
        f'font-family:Arial,Helvetica,sans-serif;font-size:{font_size}px;line-height:{height}px;'
        f'font-weight:700;color:#ffffff !important;text-decoration:none !important;white-space:nowrap;">'
        f'<span style="color:#ffffff;text-decoration:none;">{_text(text)}</span>'
        f'<span style="color:#ffffff;font-size:{font_size + 4}px;font-weight:700;text-decoration:none;">'
        f'&nbsp;&nbsp;&#8594;</span></a></td></tr></table>'
    )


def render_industry_newsletter(form, asset_base_url="", image_src=None, has_report_cover=False):
    """Render the 600 px reference layout as table-based email-safe HTML."""
    content = industry_content(form)
    image_src = image_src or {}

    def asset(filename):
        base = (asset_base_url or "").strip()
        if base.lower() == "cid":
            return f"cid:{filename}"
        return f"{base.rstrip('/')}/assets/newsletter/{filename}"

    logo = asset("ken-research-logo-color.png")
    arrow = asset("industry-arrow.png")
    report_icon = asset("industry-report-icon.png")
    tagline = "GLOBAL STRATEGIC CONSULTING &amp; MARKET INTELLIGENCE"

    development_rows = []
    for number, development in enumerate(content["developments"], start=1):
        link = _url(development["url"])
        border = "" if number == 3 else f"border-bottom:1px solid {RULE};"
        development_rows.append(f"""
          <tr>
            <td style="padding:6px 0;{border}">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="536" style="width:536px;">
                <tr>
                  <td class="ind-stack" width="184" height="90" valign="top" style="width:184px;height:90px;">
                    <a href="{link}" target="_blank"><img class="ind-img" src="{image_src.get(f'dev{number}', '')}" width="184" height="90" alt="" style="display:block;width:184px;height:90px;border:0;object-fit:cover;"></a>
                  </td>
                  <td class="ind-stack" width="322" valign="top" style="width:322px;padding:0 7px 0 15px;">
                    <div style="font-family:Arial,Helvetica,sans-serif;font-size:9px;line-height:12px;font-weight:700;letter-spacing:0.7px;text-transform:uppercase;color:{RED};">{_text(development['tag'])}</div>
                    <div style="padding-top:2px;"><a href="{link}" target="_blank" style="font-family:Georgia,'Times New Roman',serif;font-size:16px;line-height:18px;font-weight:700;color:{NAVY};text-decoration:none;">{_text(development['title'])}</a></div>
                    <div style="padding-top:3px;font-family:Arial,Helvetica,sans-serif;font-size:10px;line-height:13px;color:{GREY};">{_text(development['body'])}</div>
                  </td>
                  <td class="ind-hide" width="30" align="right" valign="middle" style="width:30px;">
                    <a href="{link}" target="_blank" aria-label="Read article"><img src="{arrow}" width="22" height="14" alt="Read" style="display:block;width:22px;height:14px;border:0;"></a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>""")
    rows_html = "".join(development_rows)

    source_html = ""
    if content["source_note"]:
        source_html = (
            f'<tr><td style="padding:0 0 2px 0;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:8px;line-height:10px;color:{LIGHT_GREY};">{_text(content["source_note"])}</td></tr>'
        )

    report_html = ""
    if content["report_title"]:
        if has_report_cover and image_src.get("report"):
            cover_html = (
                f'<img src="{image_src["report"]}" width="86" height="112" alt="Report cover" '
                f'style="display:block;width:86px;height:112px;border:0;object-fit:cover;">'
            )
        elif content["report_title"].casefold() == "ksa automotive market outlook to 2030".casefold():
            cover_html = (
                f'<img src="{asset("industry-report-cover-default.png")}" width="86" height="112" '
                f'alt="KSA Automotive Market Outlook to 2030" '
                f'style="display:block;width:86px;height:112px;border:0;">'
            )
        else:
            cover_html = f"""
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="86" height="112" bgcolor="{NAVY}" style="width:86px;height:112px;background-color:{NAVY};border:1px solid #d7dce2;">
                <tr><td valign="top" style="padding:12px 8px 5px 8px;font-family:Georgia,'Times New Roman',serif;font-size:10px;line-height:12px;font-weight:700;color:#ffffff;">{_text(content['report_title'])}</td></tr>
                <tr><td height="34" bgcolor="#b86935" style="height:34px;background-color:#b86935;border-top:4px solid {RED};font-size:1px;line-height:1px;">&nbsp;</td></tr>
              </table>"""

        report_html = f"""
      <tr>
        <td style="padding:0 32px;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="536" height="130" bgcolor="{PEACH}" style="width:536px;height:130px;background-color:{PEACH};">
            <tr>
              <td width="48" valign="top" align="left" style="width:48px;padding:8px 0 0 5px;">
                <img src="{report_icon}" width="26" height="30" alt="" style="display:block;width:26px;height:30px;border:0;">
              </td>
              <td width="352" valign="top" style="width:352px;padding:10px 8px 8px 0;">
                <div style="font-family:Arial,Helvetica,sans-serif;font-size:9px;line-height:12px;font-weight:700;letter-spacing:0.8px;text-transform:uppercase;color:{RED};">{_text(content['report_label'])}</div>
                <div style="padding-top:1px;font-family:Georgia,'Times New Roman',serif;font-size:16px;line-height:18px;font-weight:700;color:{NAVY};">{_text(content['report_title'])}</div>
                <div style="padding-top:1px;font-family:Arial,Helvetica,sans-serif;font-size:9px;line-height:11px;color:{GREY};">{_text(content['report_body'])}</div>
                <div style="padding:2px 0 10px 0;font-family:Arial,Helvetica,sans-serif;font-size:9px;line-height:11px;color:{GREY};">{_text(content['report_supporting'])}</div>
                {_button(content['report_cta_text'], content['report_cta_url'], width=168, height=22, font_size=9)}
              </td>
              <td width="136" align="center" valign="middle" style="width:136px;">{cover_html}</td>
            </tr>
          </table>
        </td>
      </tr>"""

    def social(filename, url, alt):
        return (
            f'<td style="padding-left:7px;"><a href="{_url(url)}" target="_blank">'
            f'<img src="{asset(filename)}" width="20" height="20" alt="{alt}" '
            f'style="display:block;width:20px;height:20px;border:0;"></a></td>'
        )

    footer_link_style = (
        f"font-family:Arial,Helvetica,sans-serif;font-size:8px;line-height:10px;"
        f"color:{LIGHT_GREY};text-decoration:none;"
    )
    separator = '<span style="color:#9ca3af;">&nbsp;&nbsp;|&nbsp;&nbsp;</span>'

    return f"""
<div style="display:none;font-size:1px;color:#f4f4f4;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">{_text(content['hero_title'])}</div>
<style>
  @media only screen and (max-width:600px) {{
    .ind-wrap {{ width:100% !important; }}
    .ind-stack {{ display:block !important; width:100% !important; box-sizing:border-box; }}
    .ind-img {{ width:100% !important; height:auto !important; }}
    .ind-hide {{ display:none !important; }}
  }}
</style>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#f4f4f4" style="width:100%;background-color:#f4f4f4;margin:0;padding:0;">
  <tr><td align="center" style="padding:0 4px;">
    <table role="presentation" class="ind-wrap" cellpadding="0" cellspacing="0" border="0" width="600" bgcolor="#ffffff" style="width:600px;max-width:600px;background-color:#ffffff;border:1px solid #edf0f2;">

      <!-- 600 x 59 header -->
      <tr><td style="padding:14px 16px 8px 16px;border-bottom:1px solid {RULE};">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
          <td width="2" bgcolor="{RED}" style="width:2px;background-color:{RED};font-size:1px;line-height:1px;">&nbsp;</td>
          <td valign="bottom" style="padding-left:14px;">
            <a href="{DEFAULT_URL}" target="_blank"><img src="{logo}" width="200" height="24" alt="Ken Research" style="display:block;width:200px;height:24px;border:0;"></a>
            <div style="padding-top:2px;font-family:Arial,Helvetica,sans-serif;font-size:7px;line-height:9px;letter-spacing:0.35px;color:{LIGHT_GREY};">{tagline}</div>
          </td>
          <td align="right" valign="bottom" style="font-family:Arial,Helvetica,sans-serif;">
            <div style="font-size:11px;line-height:14px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;color:{NAVY};">{_text(content['section_label'])}</div>
            <div style="padding-top:1px;font-size:9px;line-height:12px;letter-spacing:0.4px;text-transform:uppercase;color:{LIGHT_GREY};">{_text(content['issue_label'])}</div>
          </td>
        </tr></table>
      </td></tr>

      <!-- 568 x 303 hero -->
      <tr><td style="padding:0 16px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="568" height="303" bgcolor="{PEACH}" style="width:568px;height:303px;background-color:{PEACH};border-top:2px solid {RED};">
          <tr>
            <td class="ind-stack" width="282" height="303" valign="top" style="width:282px;height:303px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="282" height="301" style="width:282px;height:301px;"><tr><td valign="top" style="padding:11px 8px 9px 17px;">
                <div style="font-family:Arial,Helvetica,sans-serif;font-size:9px;line-height:12px;font-weight:700;letter-spacing:1.7px;text-transform:uppercase;color:{RED};">{_text(content['hero_kicker'])}</div>
                <div style="padding:5px 0 5px 0;font-family:Georgia,'Times New Roman',serif;font-size:23px;line-height:26px;font-weight:700;color:{NAVY};">{_text(content['hero_title'])}</div>
                <div style="width:247px;padding-bottom:8px;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:15px;color:{GREY};">{_text(content['hero_body'])}</div>
                {_button(content['hero_cta_text'], content['hero_cta_url'], width=224, height=29, font_size=11)}
              </td></tr></table>
            </td>
            <td class="ind-stack" width="286" height="303" valign="top" style="width:286px;height:303px;">
              <img class="ind-img" src="{image_src.get('hero', '')}" width="286" height="303" alt="" style="display:block;width:286px;height:303px;border:0;object-fit:cover;">
            </td>
          </tr>
        </table>
      </td></tr>

      <!-- 536 px developments section -->
      <tr><td style="padding:10px 32px 0 32px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="536" style="width:536px;"><tr>
          <td nowrap style="white-space:nowrap;padding-right:10px;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:18px;font-weight:700;text-transform:uppercase;color:{NAVY};">{_text(content['list_heading'])}</td>
          <td width="100%" valign="middle"><div style="border-top:2px solid {RED};font-size:0;line-height:0;height:0;">&nbsp;</div></td>
        </tr></table>
      </td></tr>
      <tr><td style="padding:0 32px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="536" style="width:536px;">{rows_html}{source_html}</table>
      </td></tr>

      {report_html}

      <!-- compact reference footer -->
      <tr><td style="padding:0 32px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="536" height="25" style="width:536px;height:25px;border-top:1px solid {RULE};"><tr>
          <td height="25" valign="middle" style="height:25px;">
            <img src="{logo}" width="140" height="13" alt="Ken Research" style="display:block;width:140px;height:13px;border:0;">
            <div style="padding-top:1px;font-family:Arial,Helvetica,sans-serif;font-size:6px;line-height:6px;letter-spacing:0.25px;color:{LIGHT_GREY};">{tagline}</div>
          </td>
          <td height="25" align="right" valign="middle" style="height:25px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="right"><tr>
              {social('mailmodo-linkedin.png', content['linkedin_url'], 'LinkedIn')}
              {social('mailmodo-twitter.png', content['x_url'], 'X')}
              {social('mailmodo-youtube.png', content['youtube_url'], 'YouTube')}
            </tr></table>
          </td>
        </tr></table>
      </td></tr>
      <tr><td height="10" align="center" valign="top" style="height:10px;padding:0 32px;">
        <a href="{_url(content['contact_url'])}" target="_blank" style="{footer_link_style}">Contact Us</a>{separator}<a href="{_url(content['preferences_url'])}" target="_blank" style="{footer_link_style}">Manage Preferences</a>{separator}<a href="{_url(content['unsubscribe_url'])}" target="_blank" style="{footer_link_style}">Unsubscribe</a>
      </td></tr>
    </table>
  </td></tr>
</table>
"""
