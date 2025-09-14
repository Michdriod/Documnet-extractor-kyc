from fastapi import FastAPI, Response  # Core FastAPI imports
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
try:
    # Prefer absolute import to avoid package resolution ambiguity
    from app.api.routes import router  # type: ignore
    from app.api.routes_multi import router_multi  # type: ignore
except ImportError:
    # Fallback relative import
    from .api.routes import router  # type: ignore
    from .api.routes_multi import router_multi  # type: ignore

BASE_DIR = Path(__file__).resolve().parent.parent  # Root project dir
FRONTEND_DIR = BASE_DIR / "frontend"              # Static frontend dir

app = FastAPI(title="KYC Vision Extraction API", version="0.1.0")  # Main ASGI app

# CORS (wide-open for Phase 1 dev; restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():  # Serve static assets if built
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
async def root_index():
    """Return SPA index page (fallback JSON if missing)."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Frontend not built"}

@app.get("/health")
async def health():
    return {"status": "ok"}  # Basic liveness

app.include_router(router)
app.include_router(router_multi)


# --- Noise suppression handlers (avoid 404 log noise) ---
@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools_probe():
    # Chrome devtools probe endpoint.
    return Response(status_code=204)


_EMPTY_FAVICON = bytes.fromhex(
    "0000010001001010000001002000680400001600000028000000100000002000000001002000" \
    "0000000000000000000000000000000000000000000000000000000000000000"
)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Transparent 1x1 favicon placeholder.
    return Response(content=_EMPTY_FAVICON, media_type="image/x-icon")
