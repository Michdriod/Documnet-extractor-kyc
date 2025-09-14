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
        """Load process-wide settings from environment (simple, no pydantic)."""

        OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "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")
        VISION_MODEL: str = os.getenv("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
        MAX_FILE_MB: int = int(os.getenv("MAX_FILE_MB", "15"))
        MAX_PAGES_RENDER: int = int(os.getenv("MAX_PAGES_RENDER", "4"))
        MULTI_MAX_PAGES: int = int(os.getenv("MULTI_MAX_PAGES", "40"))  # higher cap for multi-doc endpoint
        DEBUG_EXTRACTION: bool = os.getenv("DEBUG_EXTRACTION", "1") in {"1", "true", "True"}


@lru_cache
def get_settings() -> Settings:
        """Return cached singleton settings (fast repeated access)."""
        return Settings()
