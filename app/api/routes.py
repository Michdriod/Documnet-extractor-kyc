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

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form, Query
import httpx  # HTTP client for URL source fetch
from app.extraction.schemas import ErrorEnvelope, CanonicalFields, FlatExtractionResult
from app.extraction.processing import (
    validate_source,
    render_pdf_pages,
    ensure_image_format,
    assemble_field_objects,
    generate_request_id,
)
from app.extraction.prompts import build_prompt
from app.extraction.vision_model_client import vision_extractor
from app.core.config import get_settings
from app.extraction.norm_helper import normalize
import traceback
import logging

# One-time httpx debug activation guard
_HTTPX_DEBUG_ENABLED = False

logger = logging.getLogger("kyc.extract")  # Logger namespace

router = APIRouter()

@router.post(
    "/extract/vision/single",
    response_model=FlatExtractionResult,
    responses={
        400: {"model": ErrorEnvelope},  # Validation / client errors
        500: {"model": ErrorEnvelope},  # Internal unexpected failures
        502: {"model": ErrorEnvelope},  # Upstream model inference errors
    },
)
async def extract_single(
    file: UploadFile | None = File(None, description="Single image or PDF file"),
    source_url: str | None = Form(None, description="HTTP/HTTPS URL to a single PDF or image"),
    doc_type: str | None = Form(None),
    settings=Depends(get_settings),
):
    """Single fast extraction call. Exactly one of (file | source_url)."""
    request_id = generate_request_id()  # Unique trace id for correlating logs
    try:
        # --- Validate mutual exclusivity of input sources ---
        if (file is None and not source_url) or (file is not None and source_url):
            raise HTTPException(status_code=400, detail="provide_exactly_one_source")

        source_kind = "upload" if file else "url"  # label for logging
        filename = "uploaded"
        data: bytes

        if file is not None:  # Branch: direct file upload path
            # --- Read uploaded file bytes ---
            filename = file.filename or filename
            data = await file.read()
        else:  # Branch: remote URL path
            # --- Stream download remote file (size-guarded) ---
            url = source_url.strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                raise HTTPException(status_code=400, detail="invalid_url_scheme")
            try:
                max_bytes = settings.MAX_FILE_MB * 1024 * 1024
                async with httpx.AsyncClient(timeout=30) as client:
                    async with client.stream("GET", url) as resp:
                        if resp.status_code != 200:
                            raise HTTPException(status_code=400, detail="url_fetch_error")
                        filename = url.rsplit("/", 1)[-1] or "downloaded"
                        # Basic derive extension from content-type if missing
                        if "." not in filename:
                            ctype = resp.headers.get("content-type", "").lower()
                            if "pdf" in ctype:
                                filename += ".pdf"
                            elif "jpeg" in ctype or "jpg" in ctype:
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
                        data = b"".join(chunks)
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=400, detail="url_fetch_error")

        # --- File extension + size validation (ensures supported type & within limits) ---
        try:
            ext, data = validate_source(filename, data)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        truncated = False
        pages = []
        if ext == "pdf":  # PDF -> rasterize limited number of pages (config bound)
            # --- Rasterize limited PDF pages ---
            try:
                pages, truncated = render_pdf_pages(data)
            except Exception:
                raise HTTPException(status_code=400, detail="pdf_render_error")
        else:  # Image -> ensure consistent format (PNG) for model ingestion
            try:
                # --- Normalize image -> PNG for consistent model input ---
                pages = [ensure_image_format(data)]
            except Exception:
                raise HTTPException(status_code=400, detail="invalid_image")

        allowed_keys = [k for k in CanonicalFields.model_fields.keys()]  # Canonical schema keys for prompt enumeration
        # Log page sizes before model call for debugging empty extraction issues
        if settings.DEBUG_EXTRACTION:  # Optional diagnostics: page sizes + counts
            try:
                if pages:
                    logger.debug(
                        "image_pages_count=%d first_page_size_bytes=%d all_page_sizes=%s request_id=%s",
                        len(pages),
                        len(pages[0]),
                        [len(p) for p in pages],
                        request_id,
                    )
                else:
                    logger.debug("no_pages_after_preprocess request_id=%s", request_id)
            except Exception:
                logger.debug("page_size_logging_failed request_id=%s", request_id)

        # Enable verbose httpx logging once per process when debugging
        global _HTTPX_DEBUG_ENABLED  # Module-level guard avoids repeated logger setup
        if settings.DEBUG_EXTRACTION and not _HTTPX_DEBUG_ENABLED:
            try:
                httpx_logger = logging.getLogger("httpx")
                httpx_logger.setLevel(logging.DEBUG)
                if not httpx_logger.handlers:
                    # Inherit root handlers; ensure propagation
                    httpx_logger.propagate = True
                logger.debug("httpx_debug_logging_enabled request_id=%s", request_id)
                _HTTPX_DEBUG_ENABLED = True
            except Exception:
                logger.debug("httpx_debug_enable_failed request_id=%s", request_id)

        # Build single system prompt
        system_prompt = build_prompt(doc_type, allowed_keys, require_conf=settings.REQUIRE_CONFIDENCE)  # Adaptive (confidence) prompt
        if settings.DEBUG_EXTRACTION:
            try:
                logger.debug(
                    "prompt_used request_id=%s doc_type=%s system_len=%d",
                    request_id,
                    doc_type,
                    len(system_prompt),
                )
            except Exception:
                logger.debug("prompt_used request_id=%s doc_type=%s", request_id, doc_type)

        # Quick heuristic warning if model likely not vision-capable by name pattern
        if settings.DEBUG_EXTRACTION and all(tok not in settings.VISION_MODEL.lower() for tok in ["llava", "vision", "v", "mm"]):  # Simple heuristic to warn if model may not be vision-capable
            logger.debug("model_name_may_not_be_vision request_id=%s model=%s", request_id, settings.VISION_MODEL)

        try:  # Model inference (vision agent run)
            # Provide tuple (system, description) only for description injection, not as a user message
            model_result = await vision_extractor.run(system_prompt, pages)  # Vision model call
            print(model_result)
        except Exception as model_exc:
            logger.warning("model_inference_error request_id=%s error=%s", request_id, model_exc)
            raise HTTPException(status_code=502, detail="model_inference_error")

        raw = model_result.get("raw") or {}  # Model parsed output object (RawExtraction or dict-like)
        normalized = normalize(raw)  # Convert to FlatExtractionResult shape with value+confidence objects
        print(normalized)
        if not getattr(raw, 'fields', None) and model_result.get('raw_text'):
            logger.debug("empty_fields_raw_text request_id=%s raw_text=%s", request_id, model_result['raw_text'])
        raw_fields = raw.fields if hasattr(raw, 'fields') else getattr(raw, 'fields', {})  # Defensive attribute access
        raw_extra = raw.extra_fields if hasattr(raw, 'extra_fields') else getattr(raw, 'extra_fields', {})
        inferred_type = getattr(raw, 'doc_type', None) or doc_type  # Use model inference fallback

        norm_fields = assemble_field_objects(raw_fields)  # Legacy flattened assembly retained (may deprecate later)
        norm_extra = assemble_field_objects(raw_extra)

        # Dynamic accumulation of seen doc types (simple in-memory; could persist later)
        if not hasattr(extract_single, "_doc_types_seen"):  # Simple in-memory tracking of seen doc types
            setattr(extract_single, "_doc_types_seen", set())
        if inferred_type:  # Record current inferred/declared type for potential analytics
            extract_single._doc_types_seen.add(inferred_type)  # type: ignore[attr-defined]

        # Always include confidence maps now
        def flatten(d: dict) -> dict:  # Backward-compat helper (string-only mapping)
            out = {}
            for k, v in d.items():
                if isinstance(v, dict):  # FieldWithConfidence-like object
                    val = v.get("value")
                else:
                    val = v
                if val is not None and val != "":  # Skip empty / null
                    out[k] = val
            return out

        resp = normalized       # Directly return normalized structured result (includes confidence)
        # FlatExtractionResult(
        #     doc_type=inferred_type,
        #     fields=flatten(norm_fields),
        #     extra_fields=flatten(norm_extra),
        #     fields_confidence={k: v.get("confidence") for k, v in norm_fields.items()},
        #     extra_fields_confidence={k: v.get("confidence") for k, v in norm_extra.items()},
        # )
        logger.info(  # Success summary log line (stable for log aggregation)
            "extraction_success request_id=%s source_kind=%s filename=%s pages=%d doc_type=%s latency_ms=%s confidence=always",
            request_id,
            source_kind,
            filename,
            len(pages),
            # inferred_type,
            normalized.doc_type,
            model_result.get("latency_ms"),
        )
        if model_result.get('raw_text'):  # Optional debug: snippet of raw text content
            logger.debug("raw_model_text request_id=%s snippet=%s", request_id, str(model_result['raw_text'])[:500])
        return resp
    except HTTPException:
        raise  # Known client / upstream errors
    except Exception:
        traceback.print_exc()  # Fallback console trace
        logger.exception("internal_error request_id=%s", request_id)
        raise HTTPException(status_code=500, detail="internal_error")
