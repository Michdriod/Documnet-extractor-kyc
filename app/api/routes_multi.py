"""FastAPI router for multi-page / multi-document extraction endpoint.

Endpoint: POST /extract/vision/multi

Accepted sources (exactly one required):
    * file (UploadFile) – PDF or image containing one or more logical documents.
    * source_url (remote HTTP/HTTPS) – downloaded and processed similarly.
    * file_path (server-local) – restricted; assumes trusted internal path usage.

Response model consolidates consecutive pages with a shared (or inferred) doc_type
into grouped MultiPageDoc entries. Field values are merged with a first-win policy.

Error handling philosophy:
    * 400 for client-side / fetch issues (bad URL, not found, multiple sources).
    * 500 for unexpected internal failures in extraction or rendering.
    * Specific marker 'pdf_support_requires_pymupdf' when PyMuPDF is missing.

No functional changes made; only documentation and clarifying comments added.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query  # multi-source endpoint
import logging
import httpx
from pathlib import Path
from app.multidoc.extractor import extract_multi_document
from app.multidoc.multi_schemas import MultiExtractionResult
from app.extraction.norm_helper import normalize

router_multi = APIRouter()
log = logging.getLogger("kyc.multi")

@router_multi.post(
    "/extract/vision/multi",
    response_model=MultiExtractionResult,
    responses={400: {"description": "Bad Request"}, 500: {"description": "Internal Error"}},
)
async def extract_multi(
    file: UploadFile | None = File(None, description="PDF or image with multiple KYC pages"),
    source_url: str | None = Form(None, description="Remote PDF/image URL"),
    file_path: str | None = Form(None, description="Server-local path (controlled)"),
):
    provided = [x for x in (file, source_url, file_path) if x]  # enforce exactly one input
    if len(provided) != 1:
        raise HTTPException(status_code=400, detail="provide_exactly_one_source")

    try:
        if file:
            filename = file.filename or "upload"
            data = await file.read()
            log.debug("multi_input mode=file name=%s size=%d", filename, len(data))
        elif source_url:
            async with httpx.AsyncClient(timeout=45) as client:
                r = await client.get(source_url)
                r.raise_for_status()
                data = r.content
            filename = source_url.split("?")[0].split("/")[-1] or "remote"
            log.debug("multi_input mode=source_url url=%s size=%d", source_url, len(data))
        else:
            p = Path(file_path).expanduser().resolve()
            if not p.exists() or not p.is_file():
                raise HTTPException(status_code=400, detail="file_path_not_found")
            filename = p.name
            data = p.read_bytes()
            log.debug("multi_input mode=file_path path=%s size=%d", p, len(data))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"load_error:{e}")

    try:
        result = await extract_multi_document(filename, data)
        log.debug("multi_extracted groups=%d pages=%d elapsed_ms=%s", len(result.documents), result.meta.total_pages, result.meta.elapsed_ms)
        return result
    except RuntimeError as re:
        if "pymupdf_not_installed" in str(re):
            raise HTTPException(status_code=400, detail="pdf_support_requires_pymupdf")
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"multi_extraction_error:{e}")
