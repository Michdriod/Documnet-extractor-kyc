"""Core extraction helpers: file validation, PDF rendering, normalization, scoring."""

import io
import fitz  # PyMuPDF
import uuid
import re
from typing import List, Tuple, Dict, Any
from app.core.config import get_settings  # Central settings
from PIL import Image

ALLOWED_EXT = {"pdf", "jpg", "jpeg", "png", "webp"}  # Supported file extensions
DATE_RX = re.compile(r"^(19|20)\d{2}[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])$")  # Strict YYYY-MM-DD or YYYY/MM/DD
MRZ_RX = re.compile(r"^[A-Z0-9<]{20,}$")  # Coarse MRZ line: long, allowed chars
ID_RX = re.compile(r"^[A-Z0-9]{5,}$")  # Generic doc/ID token
NON_ALNUM_RX = re.compile(r"[^A-Z0-9<]")  # Strip disallowed MRZ chars

def generate_request_id() -> str:
    """Return a random hex string for correlation in logs/responses."""
    return uuid.uuid4().hex

def extension_from_filename(filename: str) -> str:
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''


def validate_source(filename: str, data: bytes) -> Tuple[str, bytes]:
    """Validate raw upload bytes and extension.

    Raises ValueError with concise error code strings that map directly to
    user-facing error.detail in API responses.
    """
    settings = get_settings()
    if not data:
        raise ValueError("empty_file")
    ext = extension_from_filename(filename)
    if ext not in ALLOWED_EXT:
        raise ValueError("unsupported_extension")
    size_mb = len(data) / (1024 * 1024)
    if size_mb > settings.MAX_FILE_MB:
        raise ValueError("file_too_large")
    return ext, data


def render_pdf_pages(data: bytes) -> Tuple[List[bytes], bool]:
    """Render a PDF (byte stream) to a list of PNG bytes.

    Returns (pages, truncated_flag). Truncation occurs when the configured
    MAX_PAGES_RENDER limit is exceeded.
    """
    settings = get_settings()
    doc = fitz.open(stream=data, filetype="pdf")
    images: List[bytes] = []
    truncated = False
    for i, page in enumerate(doc):
        if i >= settings.MAX_PAGES_RENDER:
            truncated = True
            break
    # 180dpi: balance between clarity and speed
        pix = page.get_pixmap(dpi=180)
        images.append(pix.tobytes("png"))
    return images, truncated


def ensure_image_format(data: bytes) -> bytes:
    """Normalize an image blob to PNG (RGB) to reduce model variability."""
    with Image.open(io.BytesIO(data)) as im:
        out = io.BytesIO()
        im.convert("RGB").save(out, format="PNG")
        return out.getvalue()


 # build_prompt moved to prompts.py


def normalize_value(key: str, value: str) -> str:
    """Normalize raw string value by key semantics.

    - Strip surrounding whitespace
    - Uppercase select categorical codes
    - Collapse spaces/dashes for ID-like values
    - Sanitize MRZ lines to allowed charset
    - Normalize simple date patterns to YYYY-MM-DD
    """
    if value is None:
        return value
    v = value.strip()
    if not v:
        return ""
    if key in {"nationality", "issuing_country", "sex"}:
        v = v.upper()
    if key in {"passport_number", "national_id_number", "document_number", "nin"}:
        v = re.sub(r"[\s-]", "", v.upper())
    if key.startswith("mrz_line"):
        v = NON_ALNUM_RX.sub("", v.upper())
    if re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$", v):  # Flexible 1-2 digit month/day
        y, m, d = re.split(r"[/-]", v)
        v = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return v


def score_field(key: str, value: str) -> float:
    """Heuristic confidence score (0..1) for a normalized value."""
    if not value:
        return 0.0
    score = 0.70
    if DATE_RX.match(value):
        score += 0.10
    if key.startswith("mrz_line") and MRZ_RX.match(value):
        score += 0.15
    if key in {"passport_number", "national_id_number", "document_number", "nin"}:
        if ID_RX.match(value):
            score += 0.10
        else:
            score -= 0.15
    if key not in {"sex"} and len(value) < 2:
        score -= 0.10
    return max(0.0, min(1.0, score))


def assemble_field_objects(raw: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """Convert a raw key->value mapping to value+confidence dict objects."""
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in raw.items():
        if v is None:
            continue
        nv = normalize_value(k, str(v))
        if not nv or all(ch in "-_/" for ch in nv):  # Skip effectively empty noise
            continue
        out[k] = {"value": nv, "confidence": score_field(k, nv)}
    return out


def compute_missing(doc_type: str | None, fields: Dict[str, Dict[str, Any]]) -> List[str]:  # legacy compatibility
    """Deprecated: previously returned required fields per doc type.

    Retained as no-op to avoid breaking imports; always returns empty list now.
    """
    return []

