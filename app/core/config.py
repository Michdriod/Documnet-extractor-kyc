"""Runtime configuration helpers.

This module centralizes environment-driven runtime switches so the rest of the
codebase can import a single cached Settings instance. Keeping this light
avoids tight coupling to any particular config library (can migrate later).

Env vars (optional) and their roles:
        OLLAMA_BASE_URL    -> Base URL for a local Ollama OpenAI-compatible gateway (legacy path).
        GROQ_API_KEY       -> API key for Groq model access (must be supplied via environment; never hard‑code secrets).
        VISION_MODEL       -> Identifier/name of the vision-capable model to use.
        MAX_FILE_MB        -> Upper bound for accepted upload size (reject larger uploads early).
        MAX_PAGES_RENDER   -> Max pages to rasterize for single-document flow (caps latency & cost).
        MULTI_MAX_PAGES    -> Higher per-file cap for multi-document extraction pipeline.
        DEBUG_EXTRACTION   -> Verbose logging toggle (helps diagnose prompt/model issues).
        REQUIRE_CONFIDENCE -> If true, prompt enforces {value, confidence} objects; false allows plain strings.
        DEFAULT_CONFIDENCE -> Synthesized confidence applied when model omits one (bounded 0..1).
"""

import os
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()

class Settings:
        """Central runtime switches.

        Design notes:
        - Simple class instead of pydantic BaseSettings to minimize dependencies.
        - Values read once at process start and memoized via get_settings().
        - Adjust / extend cautiously; keep only broadly useful runtime toggles here.
        """

        # Hardcoded values
        MAX_FILE_MB: int = 15  # Maximum upload size in megabytes
        MAX_PAGES_RENDER: int = 4  # Maximum number of PDF pages to render
        DEBUG_EXTRACTION: bool = True  # Enable verbose model & prompt debugging

        
        
        # ---- Core service endpoints / credentials (avoid embedding secrets in code) ----
        OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")  # Local or gateway model endpoint
        GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY")  # Provided externally; empty -> runtime error
        HF_TOKEN: str = os.environ.get("HF_TOKEN")
        
        def __init__(self):
                # Validate GROQ_API_KEY at runtime
                if not self.HF_TOKEN:
                        raise ValueError("GROQ_API_KEY is not set in the environment. Please configure it in your .env file or system environment")
        
        
        def __init__(self):
                # Validate GROQ_API_KEY at runtime
                if not self.GROQ_API_KEY:
                        raise ValueError("GROQ_API_KEY is not set in the environment. Please configure it in your .env file or system environment")

        # ---- Model selection ----
        # VISION_MODEL: str = os.getenv("VISION_MODEL", "gemma3:4b")  # Primary multimodal / vision model name
        # Alternate example retained for quick swapping (commented intentionally):
        VISION_MODEL: str = os.getenv("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")  # Alternate higher‑capacity model
        # Alternate Vision Model from Hugging Face
        # VISION_MODEL: str = os.getenv("VISION_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
        

        # ---- Resource & size guards ----
        MAX_FILE_MB: int = int(os.getenv("MAX_FILE_MB", "15"))          # Upload size cap (reject early to save memory)
        MAX_PAGES_RENDER: int = int(os.getenv("MAX_PAGES_RENDER", "4")) # Page raster cap for single-doc flow
        MULTI_MAX_PAGES: int = int(os.getenv("MULTI_MAX_PAGES", "40"))  # Higher cap for multi-doc extraction

        # ---- Diagnostics ----
        DEBUG_EXTRACTION: bool = os.getenv("DEBUG_EXTRACTION", "1") in {"1", "true", "True"}  # Verbose pipeline + model logging

        # ---- Confidence handling knobs ----
        REQUIRE_CONFIDENCE: bool = os.getenv("REQUIRE_CONFIDENCE", "1") in {"1","true","True"}  # Prompt strictness toggle
        DEFAULT_CONFIDENCE: float = float(os.getenv("DEFAULT_CONFIDENCE", "0.50"))               # Fallback when model omits confidence
        MIN_CONFIDENCE: float = 0.0  # Lower clamp bound (avoid negatives)
        MAX_CONFIDENCE: float = 1.0  # Upper clamp bound (avoid >1 values)


@lru_cache
def get_settings() -> Settings:
        """Return cached singleton Settings instance.

        Using functools.lru_cache ensures each worker process resolves environment
        variables once; subsequent imports are cheap attribute access. This keeps
        startup fast and avoids accidental per-request env lookups.
        """
        return Settings()
