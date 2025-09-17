"""Vision extraction API endpoints (ONE, BATCH, MULTI) replacing legacy single endpoint."""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from typing import List, Optional, Tuple
import re
import httpx
import asyncio
import logging
import uuid
import traceback

from app.extraction.schemas import FlatExtractionResult, CanonicalFields
from app.extraction.processing import (
    validate_source,
    render_pdf_pages,
    ensure_image_format,
)
from app.extraction.prompts import build_prompt
from app.extraction.vision_model_client import vision_extractor
from app.extraction.norm_helper import normalize
from app.core.config import get_settings

logger = logging.getLogger("kyc.extract")
router = APIRouter()

MAX_BATCH = 20  # safety guard; adjust if needed

def _req_id() -> str:
    return uuid.uuid4().hex[:12]

async def fetch_url_bytes(url: str, settings) -> Tuple[bytes, str]:
    """Fetch remote file bytes with redirect support & size guard.

    Raises HTTPException with one of: invalid_url_scheme, url_fetch_error, url_too_large.
    """
    if not (url.startswith("http://") or url.startswith("https://")):
        logger.warning("url_invalid_scheme url=%s", url)
        raise HTTPException(400, "invalid_url_scheme")
    max_bytes = settings.MAX_FILE_MB * 1024 * 1024
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    logger.warning("url_fetch_error status=%s url=%s", resp.status_code, url)
                    raise HTTPException(400, "url_fetch_error")
                final_url = str(resp.url)
                filename = final_url.rsplit("/", 1)[-1] or "remote"
                chunks: List[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        logger.warning("url_too_large url=%s size=%s max=%s", final_url, total, max_bytes)
                        raise HTTPException(400, "url_too_large")
                    chunks.append(chunk)
        return b"".join(chunks), filename
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("url_fetch_exception url=%s err=%s", url, exc)
        raise HTTPException(400, "url_fetch_error")

def _normalize_url_inputs(raw_list: List[str]) -> List[str]:
    """Split on commas/newlines, trim, drop empties, dedupe preserving order.

    Swagger or some frontends may submit a single comma-joined string or include blank
    'send empty value' artifacts. This canonicalises to a clean list.
    """
    tokens: List[str] = []
    for item in raw_list or []:
        if not item:
            continue
        for piece in re.split(r"[\n,]+", item):
            p = piece.strip()
            if p:
                tokens.append(p)
    seen = set()
    deduped: List[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped

async def process_file(upload_filename: str, raw_bytes: bytes, idx: int, *,
                       doc_type: Optional[str], settings, request_id: str,
                       multi_mode: bool = False) -> FlatExtractionResult:
    """Run full pipeline for one input file/URL bytes -> FlatExtractionResult.

    multi_mode: if True treat multi-page PDF as a single merged logical document (future hook).
    """
    try:
        ext, data = validate_source(upload_filename, raw_bytes)
    except ValueError as ve:
        raise HTTPException(400, str(ve))

    # Render pages (single doc path still processes each page; merging left simple here)
    try:
        if ext == "pdf":
            pages, _trunc = render_pdf_pages(data)
        else:
            pages = [ensure_image_format(data)]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "render_error")

    allowed_keys = list(CanonicalFields.model_fields.keys())
    prompt = build_prompt(doc_type, allowed_keys, require_conf=settings.REQUIRE_CONFIDENCE)

    try:
        model_result = await vision_extractor.run(prompt, pages)
    except Exception as exc:
        logger.warning("model_inference_error request_id=%s file=%s err=%s", request_id, upload_filename, exc)
        raise HTTPException(502, "model_inference_error")

    raw = model_result.get("raw") or {}
    normalized = normalize(raw)
    logger.info("extraction_success request_id=%s file=%s pages=%d doc_type=%s latency_ms=%s", request_id, upload_filename, len(pages), normalized.doc_type, model_result.get("latency_ms"))
    return normalized

@router.post(
    "/extract/vision/one",
    summary="Extract a SINGLE independent document (file OR url)",
    response_model=FlatExtractionResult,
    responses={400: {"description": "Must provide exactly one source"}},
)
async def extract_one(
    file: UploadFile = File(None, description="Single image/PDF"),
    url: str = Form(None, description="Single HTTP/HTTPS URL"),
    doc_type: Optional[str] = Form(None),
    settings = Depends(get_settings),
):
    # Normalize empty submissions (Swagger "send empty value" or blank form fields)
    if url is not None and url.strip() == "":
        url = None
    if file is not None and getattr(file, "filename", None) in (None, ""):
        # Treat as missing
        file = None

    if bool(file) == bool(url):  # either both present or both missing
        raise HTTPException(400, "provide_exactly_one_source")

    rid = _req_id()
    if file is not None:
        raw = await file.read()
        if not raw:
            raise HTTPException(400, "empty_file")
        return await process_file(file.filename, raw, 0, doc_type=doc_type, settings=settings, request_id=rid)

    # URL branch
    raw_bytes, name = await fetch_url_bytes(url, settings)
    return await process_file(name, raw_bytes, 0, doc_type=doc_type, settings=settings, request_id=rid)

@router.post(
    "/extract/vision/batch",
    summary="Extract MANY independent documents (files OR urls)",
    response_model=List[FlatExtractionResult],
    responses={
        400: {"description": "No inputs supplied"},
        409: {"description": "Mixed input types"}
    },
)
async def extract_batch(
    files: List[UploadFile] = File(None, description="Multiple images/PDFs (1..N)"),
    urls: List[str] = Form(None, description="Multiple HTTP/HTTPS URLs (1..N)"),
    doc_type: Optional[str] = Form(None),
    settings = Depends(get_settings),
):
    # Normalize/clean inputs (Swagger may send empty strings)
    # Robust normalization: handle comma/newline separated single field & remove empties/duplicates
    cleaned_urls = _normalize_url_inputs(urls or [])
    cleaned_files: List[UploadFile] = [f for f in (files or []) if f and getattr(f, "filename", "").strip()]

    has_files = bool(cleaned_files)
    has_urls = bool(cleaned_urls)
    if not has_files and not has_urls:
        raise HTTPException(400, "provide_files_or_urls")
    if has_files and has_urls:
        raise HTTPException(409, "choose_only_one_input_type")
    count = len(cleaned_files) if has_files else len(cleaned_urls)
    if count > MAX_BATCH:
        raise HTTPException(400, f"batch_too_large max={MAX_BATCH}")
    rid = _req_id()
    tasks = []
    if has_files:
        for idx, up in enumerate(cleaned_files):
            raw = await up.read()
            tasks.append(process_file(up.filename, raw, idx, doc_type=doc_type, settings=settings, request_id=f"{rid}-f{idx}"))
        return await asyncio.gather(*tasks)

    async def _fetch_then_process(u: str, idx: int):
        raw, name = await fetch_url_bytes(u, settings)
        return await process_file(name, raw, idx, doc_type=doc_type, settings=settings, request_id=f"{rid}-u{idx}")
    tasks = [_fetch_then_process(u, i) for i, u in enumerate(cleaned_urls)]
    return await asyncio.gather(*tasks)

# NOTE: /extract/vision/multi remains in routes_multi.py to avoid duplication.
