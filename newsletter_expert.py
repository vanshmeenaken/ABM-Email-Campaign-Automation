"""Email-safe Expert's Desk newsletter renderer."""

import base64
from html import escape
from io import BytesIO
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from PIL import Image, ImageDraw, ImageOps


DEFAULT_URL = "https://www.kenresearch.com"
CANVAS_WIDTH = 720
EXPERT_SLOTS = ("hero", "portrait", "report")
SLOT_SIZES = {"hero": (840, 480), "portrait": (472, 300), "report": (520, 400)}
IMAGE_FILES = {
    "hero": "expert-desk-hero.jpg",
    "portrait": "expert-desk-portrait.jpg",
    "report": "expert-desk-report.jpg",
}
ICON_FILES = {
    "power": "expert-takeaway-power.jpg",
    "approval": "expert-takeaway-approval.jpg",
    "localisation": "expert-takeaway-localisation.jpg",
}
# Exact icon crops from the approved reference. Keeping them embedded avoids
# replacing the supplied line icons with unrelated glyphs or third-party logos.
ICON_IMAGES_B64 = {
    "expert-takeaway-power.jpg": "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAAoADADASIAAhEBAxEB/8QAHAAAAgIDAQEAAAAAAAAAAAAAAAcFBgECCAME/8QANxAAAQIFAgIGBgsBAAAAAAAAAQIDAAQFBhEHIRIxExRBUWHSFhdxdIGRCBUiIzJCYnOEkpTR/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AOpnXEMtrcdWlDaAVKUo4AA5kmFk/rrYLTq0CtKcCVFPG1JvrScdygjBHiIsmrBKdMrqIO/1ZMcv2zC/txy7JbT2zk2bQaHPSyqY2p9U64WyleOzhG/eT3wEynXew1cqs9j3F/yRsddbCAyas9j3F/yRPWMbjmmJo3jRqPIuJUkMCRUXQpON+LI23j5r1duuVqlPRalAos/IKQszKpx0tLSr8oGBy8d/hAQ3r6sE8qs//hf8kX+17hpdz0ZmqUOcbm5J3IStGRgjmCDuCO4wvrdmtQnatREVy17flpB3pOvuS7vEtsD8JAxsfAcWe3EY0GCUrvttpKUNouWbCUpGABtyA2gGTXHJJqjTzlVLYp6GFmY6QZT0fCeLPhjMctykjbbzKH7ftrVA0pzKpYyc1wslGduAFWQmOh9V0qVpndIQkqUaZMYAGSfuzC6tdyp1HTu0fR2+KXREtU1tD7TrTTylLx+pWRjliAoL1NkFJ2tnVw/zB5o82qNTsZNsatj2zo80PWypqZpbU0m5rzpVZcWpJaUgMsdGMbjAVvmNLymahUpuQXa960akMNFXWEOttTBd7sEq7O7b2wCMXSZDOE2xq3j30eaHnoiq2jZnR2lLTMqw1MONzTM3nrCJgY4+lJ5q5bxBUhi5pat0iYq2pFFnZBjj63LpaaaLwPIAhW55bnGPGNvo/vImRfMww4l1h25JpTbiDlKxtuD2iAbKglxBSoBSVDBB3BEUNzSGwlOqWbXp3EolRwlQGT4A4EEEBhej1gKH2rXp3yV5oE6O2AncWtT/AJK80EEAeqKwVbei9N/qr/sW+hUenUGmNU+jSbEnJNZCGWU8KRnc/HxgggP/2Q==",
    "expert-takeaway-approval.jpg": "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAAoACoDASIAAhEBAxEB/8QAHAABAAEEAwAAAAAAAAAAAAAABgACAwUHAQQI/8QANBAAAQMEAQIDBQUJAAAAAAAAAQIDBAAFBhEHITESE0EVFyJRshQWMoGzRVVlcXN1kZLR/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/APUzi0NNqccUlCEgqUpR0AB6k1rWfzfgcQqQ1ekzXw4G0sw2VurWSdfD00fyNJeUN+7nJvD39myP01UGxbA7XlXDWLRJAXBeTGjykSoaEJdQ4nZB3rr39aDFu5/nSEKyoWfeMi4fZPZJguCcWd+Hz9997661qklu5zwSWrwP3dcB4OFpTM2OtpaCDr4uhA/M1Zi4JPm+d9k5Qyt/ynC055TzCvAsd0nSOhHyqzN48teI8Y5a0lx65yZbMiW/LnIQpxThR37dOw7etBtlh1t9lDrLiHGlpCkrSdhQPYg+oqvdDeG+vFeKE/u1j6aY0Bvkzrx5ko/hsj9JVD7Hj0jI+HsSYgXuZZZzMRlxiVFV134CCFJ2AoFJPT070u5P37usm0Dv2bI7f01Vr6w27HMs4dxe23O9Mw32IbK23481DTzCwnR0d+oJBB+dBl7HhuI3PG4UCw3aciFbHXWVPW6apouvbHmFxQ/GrY3vr3rIZDYYuP8AGWUsQ5dwlJchPLKpslT6gfL1oE9h07Vam4xx5NstrtUhVsVBtqSmM2mcEeDetn4VjZOgST610b3FxLGuNsng4/KgMNyIjy1NicHCpfl66eJRPYDoKBBwyd8U4n/bGPpppQzhoa4qxPp+zWPppnQUuoS4hSFpCkKGiCNgigh4gwFS1LOLWzxKOzpBA3/IHQqVKCe6PAvw/di3f6q/7XCeIsCS5sYtbSe/VCiP8bqVKB2w02w0hplCUNoSEpSkaCQOwA+VV7qVKD//2Q==",
    "expert-takeaway-localisation.jpg": "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAAoACsDASIAAhEBAxEB/8QAGwAAAgMAAwAAAAAAAAAAAAAAAAcBAwYEBQj/xAAtEAABAwQABQIGAgMAAAAAAAABAgMEAAUGEQcSEyExIkEIFDJRcYEWNFKRof/EABQBAQAAAAAAAAAAAAAAAAAAAAD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwD1Oo8qd+1KtfEy8X6dJa4e4s9eocdwtLuUqQIsZSwdEIJ7r19xV8jjXhR50InzHGSCOui3vlvx/ly0teBknL0YHEOGXrHrm02Vl603DmQ7FUVn0pUnvojR0R70DFkZnntmaVJvuCIfhI9Ti7TcEvuIT7npqAKv1W8xXIbdlNjjXazvF2HIBKSpJSpJB0UqB8EHsRS0utw4myYEhy4vYpikJCD1Za3VvuIT7qSDpO/turfhgKTw3cKHzJQblL08ry4Op9Z/Pn90DcNFTRqgVTfF2yBjpOY7lLLw7fLGzLJ/Gx6f+0n80lWm48TLNdsgxK6Y/YpTT7alsJW3NlFCdhwtsnaQkkd+/vumWh/MhFT8vxVxV2Ly/wBhyK1z6+/ZWt1h7bbrrdeKNul4hlf8lv0Fp9U+6TWFKgRwpPKllKUEAE7P0k+d0FsZrhm8sOWiwZbl04HbTMpElbfN7BRcIQBv77phfDMpw4BLDzKY7ouszmaSdhs9Tukfjx+qtNk4o3NlcSZkOPWeMscq12yE4t7R86K1aBrc4XjEDEcejWi2dQsNcylOOq5luLUdqWo+5J70He0UUUGFVwmwRx3qqxW08299mAB/rxWstdtgWeGiJbIkeHFbHpaYbDaU/odqKKDmghQCgRo96Ad0UUE0UUUH/9k=",
}

NAVY = "#111d43"
RED = "#ed1c24"
PALE = "#f3f7fb"
GREY = "#3f4759"


def _v(form, name, default=""):
    return (form.get(name, default) or "").strip()


def _text(value):
    return escape(value or "", quote=True).replace("\n", "<br>")


def _valid_url(value):
    value = (value or "").strip()
    parsed = urlparse(value)
    return value if parsed.scheme.lower() in {"http", "https"} and parsed.netloc else ""


def _is_generic_homepage(value):
    parsed = urlparse(_valid_url(value))
    host = parsed.netloc.lower().split(":", 1)[0]
    return host in {"kenresearch.com", "www.kenresearch.com"} and parsed.path.rstrip("/") == ""


def _url(value):
    return escape(_valid_url(value), quote=True)


def expert_content(form):
    content = {
        "section_label": _v(form, "exp_section_label", "Expert's Desk"),
        "issue_label": _v(form, "exp_issue_label", "November 2026 | Issue 02"),
        "brand_url": _v(form, "exp_brand_url", DEFAULT_URL),
        "utm_source": _v(form, "exp_utm_source", "newsletter"),
        "utm_medium": _v(form, "exp_utm_medium", "email"),
        "utm_campaign": _v(form, "exp_utm_campaign", "experts_desk"),
        "hero_label": _v(form, "exp_hero_label", "Expert Interview"),
        "hero_title": _v(form, "exp_hero_title"),
        "hero_body": _v(form, "exp_hero_body"),
        "hero_cta_text": _v(form, "exp_hero_cta_text", "Read the Full Expert Interview"),
        "hero_cta_url": _v(form, "exp_hero_cta_url"),
        "expert_label": _v(form, "exp_expert_label", "Meet the Expert"),
        "expert_name": _v(form, "exp_expert_name"),
        "expert_role": _v(form, "exp_expert_role"),
        "expert_company": _v(form, "exp_expert_company"),
        "takeaways_label": _v(form, "exp_takeaways_label", "Key Takeaways from the Conversation"),
        "takeaway_note": _v(form, "exp_takeaway_note", "Figures are indicative expert observations."),
        "report_label": _v(form, "exp_report_label", "Featured Market Intelligence"),
        "report_title": _v(form, "exp_report_title"),
        "report_body": _v(form, "exp_report_body"),
        "report_cta_text": _v(form, "exp_report_cta_text", "Explore the Data Centre Benchmarking"),
        "report_cta_url": _v(form, "exp_report_cta_url"),
        "contact_url": _v(form, "exp_contact_url", "https://www.kenresearch.com/contact-us"),
        "unsubscribe_url": _v(form, "exp_unsubscribe_url", DEFAULT_URL),
    }
    for number in range(1, 4):
        content[f"takeaway{number}_title"] = _v(form, f"exp_takeaway{number}_title")
        content[f"takeaway{number}_body"] = _v(form, f"exp_takeaway{number}_body")
    return content


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


def resolved_expert_links(content):
    return {
        label: _with_utms(value, content)
        for label, value in {
            "Header logo": content["brand_url"],
            "Expert interview": content["hero_cta_url"],
            "Featured intelligence": content["report_cta_url"],
            "Contact Us": content["contact_url"],
        }.items()
    }


def _complete_localisation_icon():
    """Draw a complete, padded coin-stack mark to replace the cropped source."""
    scale = 4
    canvas = Image.new("RGB", (60 * scale, 52 * scale), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    def stack(x, top, width, levels):
        x *= scale
        top *= scale
        width *= scale
        ellipse_height = 7 * scale
        level_step = 5 * scale
        stroke = 2 * scale
        bottom = top + ((levels - 1) * level_step)
        bounds = (x, top, x + width, top + ellipse_height)
        draw.ellipse(bounds, outline=(17, 17, 17), width=stroke)
        draw.line(
            (x, top + ellipse_height // 2, x, bottom + ellipse_height // 2),
            fill=(17, 17, 17), width=stroke,
        )
        draw.line(
            (x + width, top + ellipse_height // 2,
             x + width, bottom + ellipse_height // 2),
            fill=(17, 17, 17), width=stroke,
        )
        for level in range(1, levels):
            y = top + (level * level_step)
            draw.arc(
                (x, y, x + width, y + ellipse_height),
                0, 180, fill=(17, 17, 17), width=stroke,
            )
        draw.arc(
            (x, bottom, x + width, bottom + ellipse_height),
            0, 180, fill=(17, 17, 17), width=stroke,
        )

    stack(7, 29, 15, 2)
    stack(21, 22, 16, 3)
    stack(36, 13, 17, 4)
    return canvas.resize((60, 52), Image.Resampling.LANCZOS)


def expert_icon_images():
    """Return approved takeaway icons with an email-safe white padding boundary."""
    padded = {}
    for filename, encoded in ICON_IMAGES_B64.items():
        if filename == ICON_FILES["localisation"]:
            canvas = _complete_localisation_icon()
        else:
            source = Image.open(BytesIO(base64.b64decode(encoded))).convert("RGB")
            canvas = Image.new("RGB", (60, 52), (255, 255, 255))
            left = (canvas.width - source.width) // 2
            top = (canvas.height - source.height) // 2
            canvas.paste(source, (left, top))
        output = BytesIO()
        canvas.save(output, "JPEG", quality=94, optimize=True)
        padded[filename] = base64.b64encode(output.getvalue()).decode("ascii")
    return padded


def validate_expert_content(content):
    problems = []
    required = {
        "Hero headline": content["hero_title"],
        "Hero summary": content["hero_body"],
        "Expert name": content["expert_name"],
        "Expert role": content["expert_role"],
        "Expert company": content["expert_company"],
        "Featured intelligence headline": content["report_title"],
        "Featured intelligence summary": content["report_body"],
    }
    for number in range(1, 4):
        required[f"Takeaway {number} headline"] = content[f"takeaway{number}_title"]
        required[f"Takeaway {number} summary"] = content[f"takeaway{number}_body"]
    for label, value in required.items():
        if not value:
            problems.append(f"{label} is required.")
    for label, value in {
        "Header logo link": content["brand_url"],
        "Expert interview link": content["hero_cta_url"],
        "Featured intelligence link": content["report_cta_url"],
        "Contact Us link": content["contact_url"],
    }.items():
        if not _valid_url(value):
            problems.append(f"{label} must be a complete http:// or https:// URL.")
    for label, value in (
        ("Expert interview link", content["hero_cta_url"]),
        ("Featured intelligence link", content["report_cta_url"]),
    ):
        if _is_generic_homepage(value):
            problems.append(f"{label} cannot use the generic Ken Research homepage.")
    return problems


def prepare_expert_image(slot, raw, max_bytes=12 * 1024 * 1024):
    if slot not in SLOT_SIZES:
        raise ValueError(f"Unknown image slot: {slot}")
    if not raw:
        raise ValueError("The uploaded image is empty.")
    if len(raw) > max_bytes:
        raise ValueError("The uploaded image is larger than 12 MB.")
    try:
        source = Image.open(BytesIO(raw))
        source.load()
        if source.format not in {"PNG", "JPEG", "WEBP", "AVIF"}:
            raise ValueError("The upload must be a PNG, JPEG, WebP, or AVIF image.")
        minimums = {
            "hero": (600, 340),
            "portrait": (400, 450),
            "report": (400, 300),
        }
        minimum_width, minimum_height = minimums[slot]
        if source.width < minimum_width or source.height < minimum_height:
            raise ValueError(
                f"The uploaded image is too small for {slot} "
                f"(minimum {minimum_width} x {minimum_height} pixels)."
            )
        if source.width > 8192 or source.height > 8192:
            raise ValueError("The uploaded image dimensions are too large.")
        target_width, target_height = SLOT_SIZES[slot]
        if slot == "portrait":
            # Use a top-anchored crop so the expert's face and upper torso stay
            # visible while the lower body no longer makes this section tall.
            source = source.convert("RGBA")
            alpha_bounds = source.getchannel("A").getbbox()
            if alpha_bounds:
                source = source.crop(alpha_bounds)
            source = ImageOps.fit(
                source,
                (target_width, target_height),
                Image.Resampling.LANCZOS,
                centering=(0.5, 0.0),
            )
            canvas = Image.new("RGBA", (target_width, target_height), (243, 247, 251, 255))
            canvas.alpha_composite(source, (0, 0))
            source = canvas.convert("RGB")
        else:
            source = source.convert("RGB")
            ratio = target_width / target_height
            if source.width / source.height > ratio:
                width = int(source.height * ratio)
                left = (source.width - width) // 2
                source = source.crop((left, 0, left + width, source.height))
            else:
                height = int(source.width / ratio)
                top = (source.height - height) // 2
                source = source.crop((0, top, source.width, top + height))
            source = source.resize((target_width, target_height), Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(source)
        if slot == "hero":
            draw.polygon([(0, 0), (175, 0), (0, target_height)], fill=(255, 255, 255))
        elif slot == "report":
            draw.polygon(
                [(target_width - 95, 0), (target_width, 0), (target_width, target_height),
                 (target_width - 205, target_height)],
                fill=(243, 247, 251),
            )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The upload is not a valid PNG, JPEG, WebP, or AVIF image.") from exc
    output = BytesIO()
    source.save(output, "JPEG", quality=90, optimize=True)
    return output.getvalue()


def _section_heading(label):
    return f'''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td width="25"><div style="border-top:3px solid {RED};font-size:0;line-height:0;">&nbsp;</div></td>
      <td style="padding-left:10px;font-family:Arial,sans-serif;font-size:9px;line-height:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:{NAVY};white-space:nowrap;">{_text(label)}</td>
      <td style="padding-left:10px;"><div style="border-top:1px solid #aebbd1;font-size:0;line-height:0;">&nbsp;</div></td>
    </tr></table>'''


def _wrapped_line_count(value, line_units):
    lines = 0
    current = 0
    for paragraph in (value or "").splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines += 1
            continue
        for word in words:
            size = len(word)
            if current and current + 1 + size > line_units:
                lines += 1
                current = size
            else:
                current = current + (1 if current else 0) + size
        lines += 1
        current = 0
    return max(1, lines)


def _hero_height(content):
    """Keep the hero photo aligned with variable dashboard copy."""
    title_lines = _wrapped_line_count(content["hero_title"], 27)
    body_lines = _wrapped_line_count(content["hero_body"], 50)
    # The copy table is vertically centred beside the photo. Its fixed rows
    # account for the label, spacers and CTA; a small allowance provides equal
    # breathing room above and below without leaving a large gap after the CTA.
    estimated = 118 + (title_lines * 26) + (body_lines * 18)
    return max(245, min(410, estimated))


def render_expert_newsletter(form, asset_base_url="", image_src=None):
    content = expert_content(form)
    links = resolved_expert_links(content)
    image_src = image_src or {}
    hero_height = _hero_height(content)

    def asset(filename):
        base = (asset_base_url or "").strip()
        return f"cid:{filename}" if base.lower() == "cid" else f"{base.rstrip('/')}/assets/newsletter/{filename}"

    padded_icons = expert_icon_images()

    def icon_asset(filename):
        if (asset_base_url or "").strip().lower() == "cid":
            return f"cid:{filename}"
        return f"data:image/jpeg;base64,{padded_icons[filename]}"

    logo = asset("ken-research-logo-color.png")
    takeaways = ""
    icons = (ICON_FILES["power"], ICON_FILES["approval"], ICON_FILES["localisation"])
    for index in range(1, 4):
        divider = "border-left:1px solid #b9c5d9;" if index > 1 else ""
        takeaways += f'''<td class="exp-stack" width="33.33%" align="center" valign="top" style="padding:10px 24px 18px;{divider}">
          <img src="{icon_asset(icons[index - 1])}" width="52" height="45" alt="" style="display:block;width:52px;height:45px;margin:0 auto;border:0;">
          <div style="padding-top:8px;font-family:Georgia,'Times New Roman',serif;font-size:17px;line-height:21px;font-weight:700;color:{NAVY};">{_text(content[f'takeaway{index}_title'])}</div>
          <div style="padding-top:11px;font-family:Arial,sans-serif;font-size:12px;line-height:18px;color:{GREY};">{_text(content[f'takeaway{index}_body'])}</div>
        </td>'''

    hero_copy = f'''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr><td style="font-family:Arial,sans-serif;font-size:10px;line-height:12px;font-weight:700;letter-spacing:2.4px;text-transform:uppercase;color:{NAVY};"><span style="display:inline-block;width:28px;border-top:3px solid {RED};font-size:0;line-height:0;vertical-align:middle;">&nbsp;</span>&nbsp;&nbsp;{_text(content['hero_label'])}</td></tr>
      <tr><td height="15" style="height:15px;font-size:0;line-height:0;">&nbsp;</td></tr>
      <tr><td style="font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:26px;font-weight:700;color:{NAVY};">{_text(content['hero_title'])}</td></tr>
      <tr><td height="13" style="height:13px;font-size:0;line-height:0;">&nbsp;</td></tr>
      <tr><td style="font-family:Arial,sans-serif;font-size:12px;line-height:18px;color:{GREY};">{_text(content['hero_body'])}</td></tr>
      <tr><td height="18" style="height:18px;font-size:0;line-height:0;">&nbsp;</td></tr>
      <tr><td><table role="presentation" width="270" cellpadding="0" cellspacing="0" border="0"><tr><td height="36" align="center" bgcolor="{RED}" style="height:36px;border-radius:5px;"><a href="{_url(links['Expert interview'])}" style="display:block;font-family:Arial,sans-serif;font-size:13px;line-height:36px;font-weight:700;color:#fff;text-decoration:none;">{_text(content['hero_cta_text'])}&nbsp;&nbsp;&#8594;</a></td></tr></table></td></tr>
    </table>'''

    report_copy = f'''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PALE}" style="background-color:{PALE};">
      <tr><td bgcolor="{PALE}" style="padding:0 0 14px 0;background-color:{PALE};font-family:Arial,sans-serif;font-size:10px;line-height:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:{NAVY};">{_text(content['report_label'])}</td></tr>
      <tr><td bgcolor="{PALE}" style="padding:0 0 14px 0;background-color:{PALE};font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:27px;font-weight:700;color:{NAVY};">{_text(content['report_title'])}</td></tr>
      <tr><td bgcolor="{PALE}" style="padding:0 0 18px 0;background-color:{PALE};font-family:Arial,sans-serif;font-size:11.5px;line-height:18px;color:{GREY};">{_text(content['report_body'])}</td></tr>
      <tr><td bgcolor="{PALE}" style="background-color:{PALE};"><a href="{_url(links['Featured intelligence'])}" style="font-family:Arial,sans-serif;font-size:12px;line-height:16px;font-weight:700;color:{RED};text-decoration:underline;">{_text(content['report_cta_text'])}&nbsp;&nbsp;&#8594;</a></td></tr>
    </table>'''

    return f'''<div style="display:none;font-size:1px;color:#fff;max-height:0;overflow:hidden;">{_text(content['hero_title'])}</div>
<style>@media only screen and (max-width:600px){{.exp-wrap{{width:100%!important}}.exp-stack{{display:block!important;width:100%!important;box-sizing:border-box!important}}.exp-img{{width:100%!important;height:auto!important}}}}</style>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#eef3f8" style="margin:0;padding:0;background:#eef3f8;"><tr><td align="center">
<table role="presentation" class="exp-wrap" width="720" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff" style="width:720px;max-width:720px;background:#fff;">
  <tr><td style="padding:12px 16px 10px;border-bottom:3px solid {RED};"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
    <td valign="middle"><a href="{_url(links['Header logo'])}"><img src="{logo}" width="220" height="27" alt="Ken Research" style="display:block;border:0;"></a><div style="padding-top:2px;font-family:Arial,sans-serif;font-size:8px;color:#333;">Global Strategic Consulting &amp; Market Intelligence</div></td>
    <td width="1" bgcolor="{NAVY}" style="width:1px;"></td><td align="right" valign="middle" style="padding-left:16px;"><div style="font-family:Arial,sans-serif;font-size:18px;line-height:20px;font-weight:700;letter-spacing:2.5px;color:{NAVY};text-transform:uppercase;">{_text(content['section_label'])}</div><div style="padding-top:5px;font-family:Arial,sans-serif;font-size:11px;color:{NAVY};text-transform:uppercase;">{_text(content['issue_label'])}</div></td>
  </tr></table></td></tr>
  <tr><td><table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="table-layout:fixed;"><tr>
    <td class="exp-stack" width="320" valign="middle" style="padding:0 16px 0 20px;">{hero_copy}</td>
    <td class="exp-stack" width="400" valign="top"><img class="exp-img" src="{image_src.get('hero','')}" width="400" height="{hero_height}" alt="Expert interview" style="display:block;width:400px;height:{hero_height}px;object-fit:cover;border:0;"></td>
  </tr></table></td></tr>
  <tr><td bgcolor="{PALE}" style="padding:10px 22px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
    <td class="exp-stack" width="205" valign="middle"><img class="exp-img" src="{image_src.get('portrait','')}" width="200" height="127" alt="{_text(content['expert_name'])}" style="display:block;width:200px;height:127px;object-fit:cover;object-position:center top;border:0;"></td>
    <td class="exp-stack" valign="middle" style="padding:6px 22px 6px 26px;"><div style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:2.2px;text-transform:uppercase;color:{NAVY};"><span style="display:inline-block;height:14px;border-left:3px solid {RED};vertical-align:-3px;margin-right:16px;">&nbsp;</span>{_text(content['expert_label'])}</div><div style="padding-top:8px;font-family:Georgia,'Times New Roman',serif;font-size:28px;line-height:32px;font-weight:700;color:{NAVY};">{_text(content['expert_name'])}</div><div style="padding-top:5px;font-family:Arial,sans-serif;font-size:13px;line-height:18px;color:{GREY};">{_text(content['expert_role'])}<br><strong style="color:{NAVY};">{_text(content['expert_company'])}</strong></div></td>
  </tr></table></td></tr>
  <tr><td style="padding:22px 18px 10px;">{_section_heading(content['takeaways_label'])}</td></tr>
  <tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{takeaways}</tr></table><div style="padding:2px 24px 20px;font-family:Arial,sans-serif;font-size:10px;line-height:15px;font-style:italic;color:{GREY};">{_text(content['takeaway_note'])}</div></td></tr>
  <tr><td style="padding:4px 18px 22px;"><table role="presentation" width="684" cellpadding="0" cellspacing="0" bgcolor="{PALE}" style="width:684px;background:{PALE};border-radius:6px;"><tr>
    <td class="exp-stack" width="260" valign="middle" bgcolor="{PALE}" style="padding:16px;background-color:{PALE};"><img class="exp-img" src="{image_src.get('report','')}" width="235" height="190" alt="Featured market intelligence" style="display:block;width:235px;height:190px;object-fit:cover;border:0;"></td>
    <td class="exp-stack" valign="top" bgcolor="{PALE}" style="padding:20px 22px 20px 8px;background-color:{PALE};">{report_copy}</td>
  </tr></table></td></tr>
  <tr><td style="padding:13px 16px 16px;border-top:1px solid {NAVY};" align="right"><a href="{_url(links['Contact Us'])}" style="font-family:Arial,sans-serif;font-size:11px;color:#222;text-decoration:none;">Contact Us</a><span style="color:#aaa;">&nbsp;&nbsp;|&nbsp;&nbsp;</span><a href="{_url(content['unsubscribe_url'])}" style="font-family:Arial,sans-serif;font-size:11px;color:#222;text-decoration:none;">Unsubscribe</a></td></tr>
</table></td></tr></table>'''
