"""Image generation for the Industry Intelligence newsletter.

Newsletter copy can be sent to the optional NVIDIA API, or users can upload
their own images through the dashboard for local normalization and storage.

Environment variables:
    NVIDIA_API_KEY            NVIDIA API key (required)
    NVIDIA_IMAGE_ENDPOINT     Hosted generation endpoint
    NVIDIA_IMAGE_MODEL        Optional model name included in the request
    NVIDIA_IMAGE_RESOLUTION   Cosmos resolution preset (default: 720_1_1)
    NVIDIA_IMAGE_STEPS        Inference steps (default: 4 for FLUX)
    NVIDIA_IMAGE_TIMEOUT      Request timeout in seconds (default: 180)

When the key is missing, a neutral placeholder is returned and flagged. The
dashboard may display it, but the application never sends placeholder images.
"""

import base64
import binascii
import os
import random
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFilter

DEFAULT_ENDPOINT = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell"
DEFAULT_MODEL = "black-forest-labs/flux.1-schnell"

HERO_BG = (253, 247, 241)
HERO_FADE_WIDTH = 0.45
HERO_EDGE_FADE = 0.08

# Final pixel sizes (2x the displayed size for sharp rendering on retina screens).
SLOT_SIZES = {
    # Exactly 2x the dimensions used by the 600 px reference email.
    "hero": (572, 606),
    "dev1": (368, 180),
    "dev2": (368, 180),
    "dev3": (368, 180),
}
SLOTS = tuple(SLOT_SIZES)

STYLE = (
    "Minimalist professional editorial photograph for a corporate market-intelligence "
    "newsletter. Clean uncluttered composition, soft natural lighting, refined muted "
    "colors with subtle warm accents, premium business magazine photography, realistic, "
    "sharp focus. No text, letters, numbers, charts, logos, watermarks, borders, collages, "
    "or recognizable faces."
)
HERO_HINT = (
    "Wide establishing composition with the main subject on the right half and calm "
    "open space on the left for an editorial text overlay."
)


class ImageGenError(Exception):
    """Raised when the configured image provider cannot return a usable image."""


def provider_configured():
    return bool(os.getenv("NVIDIA_API_KEY"))


def provider_name():
    if not provider_configured():
        return "Not configured"
    return f"NVIDIA {(os.getenv('NVIDIA_IMAGE_MODEL') or DEFAULT_MODEL).strip()}"


def _env_int(name, default, minimum, maximum):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _error_detail(response):
    try:
        payload = response.json()
    except ValueError:
        return (response.text or response.reason or "Unknown provider response")[:500]
    if isinstance(payload, dict):
        for key in ("detail", "message", "error", "title"):
            if payload.get(key):
                return str(payload[key])[:500]
    return str(payload)[:500]


def _decode_image(payload):
    """Extract an image from the response variants used by hosted NVIDIA NIMs."""
    encoded = payload.get("b64_image") or payload.get("image")
    if isinstance(encoded, list):
        encoded = encoded[0] if encoded else None
    if isinstance(encoded, dict):
        encoded = encoded.get("b64_image") or encoded.get("image") or encoded.get("data")
    if not encoded and isinstance(payload.get("data"), list) and payload["data"]:
        item = payload["data"][0]
        if isinstance(item, dict):
            encoded = item.get("b64_image") or item.get("b64_json") or item.get("image")
    if not encoded and isinstance(payload.get("artifacts"), list) and payload["artifacts"]:
        item = payload["artifacts"][0]
        if isinstance(item, dict):
            encoded = item.get("base64") or item.get("b64_image") or item.get("image")
    if not isinstance(encoded, str) or not encoded.strip():
        raise ImageGenError("NVIDIA returned no image data.")
    encoded = encoded.strip()
    if encoded.startswith("data:"):
        encoded = encoded.split(",", 1)[-1]
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageGenError("NVIDIA returned invalid base64 image data.") from exc


def _nvidia_generate(prompt):
    endpoint = (os.getenv("NVIDIA_IMAGE_ENDPOINT") or DEFAULT_ENDPOINT).strip()
    is_cosmos = "/cosmos/" in endpoint.lower()
    timeout = _env_int("NVIDIA_IMAGE_TIMEOUT", 180, 30, 600)
    seed = random.SystemRandom().randint(1, 2_147_483_647)
    if is_cosmos:
        payload = {
            "model_mode": "text2image",
            "prompt": prompt[:4000],
            "resolution": (os.getenv("NVIDIA_IMAGE_RESOLUTION") or "720_1_1").strip(),
            "num_inference_steps": _env_int("NVIDIA_IMAGE_STEPS", 50, 1, 50),
            "seed": seed,
        }
    else:
        payload = {
            "prompt": prompt[:4000],
            "height": 1024,
            "width": 1024,
            "cfg_scale": 0,
            "mode": "base",
            "image": None,
            "samples": 1,
            "seed": seed,
            "steps": _env_int("NVIDIA_IMAGE_STEPS", 4, 1, 4),
        }

    headers = {
        "Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    # Never automatically retry a generation. A timeout does not prove NVIDIA
    # stopped the first job, so retrying could consume a second trial request.
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    except requests.Timeout as exc:
        raise ImageGenError(
            f"NVIDIA did not return an image within {timeout} seconds. No automatic retry was made."
        ) from exc
    except requests.RequestException as exc:
        raise ImageGenError(f"Could not reach NVIDIA's image endpoint: {exc}") from exc

    if response.ok:
        try:
            return _decode_image(response.json())
        except ValueError as exc:
            raise ImageGenError("NVIDIA returned a non-JSON success response.") from exc

    detail = _error_detail(response)
    last_error = f"HTTP {response.status_code}: {detail}"

    if last_error and "HTTP 404:" in last_error:
        raise ImageGenError(
            "NVIDIA's hosted image endpoint returned HTTP 404. Confirm that "
            "NVIDIA_IMAGE_ENDPOINT is enabled for this API key, then try again."
        )
    raise ImageGenError(f"NVIDIA image generation failed ({last_error or 'unknown error'}).")


def _fit(img, size):
    """Center-crop to the target aspect ratio, then resize."""
    target_width, target_height = size
    img = img.convert("RGB")
    width, height = img.size
    target_ratio = target_width / target_height
    if width / height > target_ratio:
        new_width = int(height * target_ratio)
        img = img.crop(((width - new_width) // 2, 0, (width - new_width) // 2 + new_width, height))
    else:
        new_height = int(width / target_ratio)
        img = img.crop((0, (height - new_height) // 2, width, (height - new_height) // 2 + new_height))
    return img.resize(size, Image.Resampling.LANCZOS)


def _fade_hero(img, bg=HERO_BG, left=HERO_FADE_WIDTH, vertical=HERO_EDGE_FADE):
    """Bake an Outlook-safe transition from the peach text panel into the hero photo."""
    width, height = img.size

    def smooth(value):
        value = max(0.0, min(1.0, value))
        return value * value * (3 - 2 * value)

    left_width = max(1, int(width * left))
    edge_height = max(1, int(height * vertical))
    mask = Image.new("L", (width, height), 255)
    pixels = mask.load()
    for y in range(height):
        alpha_y = smooth(min(y, height - 1 - y) / edge_height)
        for x in range(width):
            pixels[x, y] = int(255 * smooth(x / left_width) * alpha_y)
    base = Image.new("RGB", (width, height), bg)
    base.paste(img, (0, 0), mask)
    return base


def _to_jpeg(img):
    buffer = BytesIO()
    img.save(buffer, "JPEG", quality=86, optimize=True)
    return buffer.getvalue()


def _placeholder(slot):
    """Neutral abstract image used only for a dashboard with no configured provider."""
    size = SLOT_SIZES[slot]
    width, height = size
    img = Image.new("RGB", size, (236, 238, 242))
    draw = ImageDraw.Draw(img)
    for i in range(6):
        x0 = int(width * (0.1 + 0.13 * i))
        bar_height = int(height * (0.25 + 0.09 * ((i * 3) % 5)))
        draw.rectangle(
            [x0, height - bar_height - int(height * 0.08), x0 + int(width * 0.07), height - int(height * 0.08)],
            fill=(176, 183, 196) if i % 3 else (214, 47, 47),
        )
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    if slot == "hero":
        img = _fade_hero(img)
    return _to_jpeg(img)


def _prompt(slot, title, body, industry):
    subject = " ".join(f"{industry}. {title}. {body}".split())
    composition = HERO_HINT if slot == "hero" else "Landscape editorial composition with one clear focal subject."
    return f"Editorial subject: {subject[:2200]} {composition} {STYLE}"


def prepare_uploaded_image(slot, raw, max_bytes=12 * 1024 * 1024):
    """Validate and normalize a dashboard-uploaded image to its email slot."""
    if slot not in SLOT_SIZES:
        raise ValueError(f"Unknown image slot: {slot}")
    if not raw:
        raise ImageGenError("The uploaded image is empty.")
    if len(raw) > max_bytes:
        raise ImageGenError("The uploaded image is larger than 12 MB.")
    try:
        source = Image.open(BytesIO(raw))
        if source.format not in {"PNG", "JPEG", "WEBP"}:
            raise ImageGenError("The upload must be a PNG, JPEG, or WebP image.")
        source.load()
        if source.width < 200 or source.height < 120:
            raise ImageGenError("The uploaded image is too small (minimum 200 x 120 pixels).")
        if source.width > 8192 or source.height > 8192:
            raise ImageGenError("The uploaded image dimensions are too large.")
        image = _fit(source, SLOT_SIZES[slot])
    except ImageGenError:
        raise
    except Exception as exc:
        raise ImageGenError("The upload is not a valid PNG, JPEG, or WebP image.") from exc
    if slot == "hero":
        image = _fade_hero(image)
    return _to_jpeg(image)


def generate_slot(slot, title, body, industry=""):
    """Return ``(jpeg_bytes, is_placeholder)`` for one image slot."""
    if slot not in SLOT_SIZES:
        raise ValueError(f"Unknown image slot: {slot}")
    if not provider_configured():
        return _placeholder(slot), True

    raw = _nvidia_generate(_prompt(slot, title, body, industry))
    try:
        image = _fit(Image.open(BytesIO(raw)), SLOT_SIZES[slot])
    except Exception as exc:
        raise ImageGenError("NVIDIA returned image data that could not be opened.") from exc
    if slot == "hero":
        # The fade is part of the image itself. CSS gradients/background blending
        # are inconsistent in Outlook and several other desktop email clients.
        image = _fade_hero(image)
    return _to_jpeg(image), False


def generate_images(specs, industry="", slots=None):
    """Generate requested slots from ``{slot: (headline, summary)}`` specs."""
    wanted = [slot for slot in (slots or SLOTS) if slot in specs]
    with ThreadPoolExecutor(max_workers=min(2, max(1, len(wanted)))) as pool:
        futures = {
            slot: pool.submit(generate_slot, slot, specs[slot][0], specs[slot][1], industry)
            for slot in wanted
        }
        return {slot: future.result() for slot, future in futures.items()}
