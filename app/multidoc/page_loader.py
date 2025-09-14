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
    """Return list of PNG page bytes for PDF or image. Uses existing render_pdf_pages if available."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            from app.extraction.processing import render_pdf_pages
            pages, truncated = render_pdf_pages(data)
            # If truncated because of single-doc cap, reopen PDF and render remaining up to MULTI_MAX_PAGES
            settings = get_settings()
            if truncated and len(pages) < settings.MULTI_MAX_PAGES:  # try to fetch remaining pages beyond single-doc cap
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
