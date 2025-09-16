"""Single-document extraction endpoint.

High-level flow:
    1. Accept exactly ONE source: an uploaded file or a remote URL.
    2. Stream / read bytes (with size guard for URLs) and infer extension when missing.
    3. Validate file type + size then (if PDF) rasterize a limited number of pages.
    4. Build a system prompt enumerating canonical field keys (confidence optional via flag).
    5. Send page images to the vision model; capture structured raw output.
    6. Normalize raw output (value + confidence objects) via normalize() helper.
    7. Log diagnostics (prompt length, page sizes, latency) if DEBUG_EXTRACTION enabled.
    8. Return FlatExtractionResult-style object (here, normalized) to client.

Note: All original code preserved; only explanatory comments added per request.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from typing import List
import httpx  # HTTP client for URL source fetch
from app.extraction.schemas import ErrorEnvelope, CanonicalFields, FlatExtractionResult
from app.extraction.processing import (
    validate_source,
    render_pdf_pages,
    ensure_image_format,
    generate_request_id,
)
from app.extraction.prompts import build_prompt
from app.extraction.vision_model_client import vision_extractor
from app.core.config import get_settings
from app.extraction.norm_helper import normalize
import traceback
import logging
import asyncio

# One-time httpx debug activation guard
_HTTPX_DEBUG_ENABLED = False

logger = logging.getLogger("kyc.extract")  # Logger namespace

router = APIRouter()

@router.post(
    "/extract/vision/single",
    response_model=List[FlatExtractionResult],  # Always return a list (single-file -> list of one)
    responses={
        400: {"model": ErrorEnvelope},  # Validation / client errors
        500: {"model": ErrorEnvelope},  # Internal unexpected failures
        502: {"model": ErrorEnvelope},  # Upstream model inference errors
    },
)
async def extract_single(
    files: List[UploadFile] = File(None, description="One or more image/PDF files (field name 'files')"),
    file: UploadFile | None = File(None, description="Backward compatible single file field 'file'"),
    source_url: str | None = Form(None, description="HTTP/HTTPS URL to a single PDF or image (legacy single)"),
    source_urls: List[str] | None = Form(None, description="Multiple HTTP/HTTPS URLs (repeat field)"),
    doc_type: str | None = Form(None),
    settings=Depends(get_settings),
):
    """Concurrent extraction for one or more files (or exactly one remote URL).

    Returns a list of normalized FlatExtractionResult objects. For backward
    compatibility, clients that previously received a single object will now
    receive a single-item list.
    """
    base_request_id = generate_request_id()

    # Merge legacy single file param into files list if provided
    if file is not None:
        if files:
            files.append(file)
        else:
            files = [file]

    # --- Validate exclusivity (treat empty list as no files) ---
    has_files = bool(files and any(f is not None for f in files))
    # Normalize multi URLs list (filter empties/whitespace)
    clean_multi_urls = []
    if source_urls:
        for u in source_urls:
            if u and u.strip():
                clean_multi_urls.append(u.strip())
    has_multi_urls = len(clean_multi_urls) > 0
    has_single_url = bool(source_url)

    # Exclusivity: exactly one of (files, single_url, multi_urls)
    used = sum([1 if has_files else 0, 1 if has_single_url else 0, 1 if has_multi_urls else 0])
    if used != 1:
        raise HTTPException(status_code=400, detail="provide_exactly_one_source_variant")

    # Enable verbose httpx logging once per process when debugging (shared across tasks)
    global _HTTPX_DEBUG_ENABLED
    if settings.DEBUG_EXTRACTION and not _HTTPX_DEBUG_ENABLED:
        try:
            httpx_logger = logging.getLogger("httpx")
            httpx_logger.setLevel(logging.DEBUG)
            if not httpx_logger.handlers:
                httpx_logger.propagate = True
            logger.debug("httpx_debug_logging_enabled request_id=%s", base_request_id)
            _HTTPX_DEBUG_ENABLED = True
        except Exception:
            logger.debug("httpx_debug_enable_failed request_id=%s", base_request_id)

    allowed_keys = [k for k in CanonicalFields.model_fields.keys()]

    async def fetch_remote(url: str) -> tuple[str, bytes]:
        """Download remote file into memory with size guard."""
        if not (url.startswith("http://") or url.startswith("https://")):
            raise HTTPException(status_code=400, detail="invalid_url_scheme")
        try:
            max_bytes = settings.MAX_FILE_MB * 1024 * 1024
            async with httpx.AsyncClient(timeout=30) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        raise HTTPException(status_code=400, detail="url_fetch_error")
                    filename = url.rsplit("/", 1)[-1] or "downloaded"
                    if "." not in filename:  # Derive basic extension from content-type
                        ctype = resp.headers.get("content-type", "").lower()
                        if "pdf" in ctype:
                            filename += ".pdf"
                        elif any(t in ctype for t in ["jpeg", "jpg"]):
                            filename += ".jpg"
                        elif "png" in ctype:
                            filename += ".png"
                        elif "webp" in ctype:
                            filename += ".webp"
                    chunks = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise HTTPException(status_code=400, detail="url_too_large")
                        chunks.append(chunk)
                    return filename, b"".join(chunks)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="url_fetch_error")

    async def process_file(upload_filename: str, raw_bytes: bytes, idx: int) -> FlatExtractionResult:
        """Full pipeline for a single file -> normalized extraction result."""
        request_id = f"{base_request_id}-{idx}"
        try:
            # Validate + possibly mutate bytes (ext inference)
            try:
                ext, data = validate_source(upload_filename, raw_bytes)
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))

            # Render pages
            try:
                if ext == "pdf":
                    pages, truncated = render_pdf_pages(data)
                else:
                    pages = [ensure_image_format(data)]
                    truncated = False
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=400, detail="render_error")

            if settings.DEBUG_EXTRACTION:
                try:
                    logger.debug(
                        "pre_model_metrics request_id=%s filename=%s pages=%d page_sizes=%s truncated=%s",
                        request_id,
                        upload_filename,
                        len(pages),
                        [len(p) for p in pages],
                        truncated,
                    )
                except Exception:
                    logger.debug("metrics_logging_failed request_id=%s", request_id)

            system_prompt = build_prompt(doc_type, allowed_keys, require_conf=settings.REQUIRE_CONFIDENCE)
            if settings.DEBUG_EXTRACTION:
                logger.debug(
                    "prompt_used request_id=%s filename=%s len=%d doc_type=%s",
                    request_id,
                    upload_filename,
                    len(system_prompt),
                    doc_type,
                )

            # Model call
            try:
                model_result = await vision_extractor.run(system_prompt, pages)
            except Exception as exc:
                logger.warning("model_inference_error request_id=%s error=%s", request_id, exc)
                raise HTTPException(status_code=502, detail="model_inference_error")

            raw = model_result.get("raw") or {}
            normalized = normalize(raw)

            logger.info(
                "extraction_success request_id=%s filename=%s pages=%d doc_type=%s latency_ms=%s confidence=always",
                request_id,
                upload_filename,
                len(pages),
                normalized.doc_type,
                model_result.get("latency_ms"),
            )
            return normalized
        except HTTPException:
            raise
        except Exception:
            traceback.print_exc()
            logger.exception("internal_error_single request_id=%s", request_id)
            raise HTTPException(status_code=500, detail="internal_error")

    # --- Remote URL single path (wrap into list for unified return) ---
    if source_url:
        filename, data = await fetch_remote(source_url.strip())
        result = await process_file(filename, data, 0)
        return [result]

    if clean_multi_urls:
        # Fetch all concurrently then process each
        async def fetch_and_process(idx_url: tuple[int, str]):
            idx, url = idx_url
            fname, bytes_ = await fetch_remote(url)
            return await process_file(fname, bytes_, idx)
        results = await asyncio.gather(*[fetch_and_process(t) for t in enumerate(clean_multi_urls)])
        return list(results)

    # --- Multi upload path ---
    tasks = []
    for idx, upload in enumerate(files):
        if upload is None:
            continue
        fname = upload.filename or f"upload_{idx}"
        raw_bytes = await upload.read()
        tasks.append(process_file(fname, raw_bytes, idx))

    # Run concurrently
    results = await asyncio.gather(*tasks)
    return list(results)
