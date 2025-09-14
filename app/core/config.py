"""Runtime configuration helpers.

Env vars (optional):
        OLLAMA_BASE_URL   Local Ollama (OpenAI compatible) base URL.
        VISION_MODEL      Vision model name.
        MAX_FILE_MB       Upload size cap (MB).
        MAX_PAGES_RENDER  Max PDF pages rasterized.
"""

import os
from functools import lru_cache


class Settings:
        """Central runtime switches.

        Keep minimal: easy to port later to pydantic-settings if needed.
        Each attr reads once then cached by get_settings().
        """

        OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")  # Local model endpoint (legacy path)
        GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "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")  # Required for Groq model
        VISION_MODEL: str = os.getenv("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")  # Model identifier
        MAX_FILE_MB: int = int(os.getenv("MAX_FILE_MB", "15"))  # Upload size cap
        MAX_PAGES_RENDER: int = int(os.getenv("MAX_PAGES_RENDER", "4"))  # Single-doc PDF cap
        MULTI_MAX_PAGES: int = int(os.getenv("MULTI_MAX_PAGES", "40"))  # Multi-doc higher limit
        DEBUG_EXTRACTION: bool = os.getenv("DEBUG_EXTRACTION", "1") in {"1", "true", "True"}  # Verbose logs toggle


@lru_cache
def get_settings() -> Settings:
        """Return cached singleton settings (fast repeated access)."""
        return Settings()
