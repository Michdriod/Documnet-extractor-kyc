"""Page loading / rasterization utilities for multi-document extraction.

Responsibilities:
    * Convert uploaded PDF or image bytes into a list of page PNG byte blobs.
    * Respect MULTI_MAX_PAGES limit from settings (prevents runaway processing).
    * Reuse the single-document PDF rendering code path when available to avoid
        duplication (render_pdf_pages) and then extend beyond its single-doc cap.

Design notes:
    * We optimistically attempt to import pymupdf (fitz) only when needed.
    * On PDF truncation in single-doc path, we reopen and continue rendering until
        the multi-doc limit to provide full coverage.
    * Error handling is deliberately forgiving: failure to process an image falls
        back to returning the raw bytes – downstream code can still attempt model OCR.

No logic altered; only explanatory comments were added per maintenance request.
"""

from typing import List  # simple list of page PNG bytes returned
from app.core.config import get_settings
from io import BytesIO
from PIL import Image

def bytes_image_to_png(data: bytes) -> bytes:
    img = Image.open(BytesIO(data))
    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()

def file_bytes_to_pages(filename: str, data: bytes) -> List[bytes]:
    """Return list of PNG page bytes for PDF or image.

    Strategy:
      1. If PDF -> try reuse render_pdf_pages (single-doc pipeline) for first N pages.
      2. If truncated and multi-doc limit higher, continue rendering remaining pages.
      3. If any PDF path fails, fallback to manual pymupdf rendering.
      4. Non-PDF -> attempt image normalization to PNG (else return raw bytes).
    """
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            from app.extraction.processing import render_pdf_pages
            pages, truncated = render_pdf_pages(data)
            settings = get_settings()
            if truncated and len(pages) < settings.MULTI_MAX_PAGES:
                try:
                    import fitz  # type: ignore
                    remaining: List[bytes] = []
                    with fitz.open(stream=data, filetype="pdf") as doc:
                        for i, page in enumerate(doc):
                            if i < len(pages):
                                continue
                            if i >= settings.MULTI_MAX_PAGES:
                                break
                            pix = page.get_pixmap(dpi=180)
                            remaining.append(pix.tobytes("png"))
                    pages.extend(remaining)
                except Exception:
                    pass
            return pages[: get_settings().MULTI_MAX_PAGES]
        except Exception:
            try:
                import fitz  # type: ignore
            except ImportError as e:
                raise RuntimeError("pymupdf_not_installed") from e
            out: List[bytes] = []
            settings = get_settings()
            with fitz.open(stream=data, filetype="pdf") as doc:
                for i, page in enumerate(doc):
                    if i >= settings.MULTI_MAX_PAGES:
                        break
                    pix = page.get_pixmap(dpi=180)
                    out.append(pix.tobytes("png"))
            return out
    # Image or other -> single page attempt
    try:
        return [bytes_image_to_png(data)]
    except Exception:
        return [data]
