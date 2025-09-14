from fastapi import APIRouter, UploadFile, File, Form, HTTPException  # multi-source endpoint
import httpx
from pathlib import Path
from app.multidoc.extractor import extract_multi_document
from app.multidoc.multi_schemas import MultiExtractionResult

router_multi = APIRouter()

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
        elif source_url:
            async with httpx.AsyncClient(timeout=45) as client:
                r = await client.get(source_url)
                r.raise_for_status()
                data = r.content
            filename = source_url.split("?")[0].split("/")[-1] or "remote"
        else:
            p = Path(file_path).expanduser().resolve()
            if not p.exists() or not p.is_file():
                raise HTTPException(status_code=400, detail="file_path_not_found")
            filename = p.name
            data = p.read_bytes()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"load_error:{e}")

    try:
        return await extract_multi_document(filename, data)
    except RuntimeError as re:
        if "pymupdf_not_installed" in str(re):
            raise HTTPException(status_code=400, detail="pdf_support_requires_pymupdf")
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"multi_extraction_error:{e}")
