"""Normalization layer converting RawExtraction -> FlatExtractionResult.

Why separate module?:
    Keeps transformation logic isolated from both the model client and API
    route handlers. This makes it easy to unit test normalization and evolve
    strategies (e.g., auto‑generated heuristics, enrichment) without touching
    model invocation code.

Flows handled:
    - Accepts permissive raw.fields / raw.extra_fields values (strings, dicts, etc.).
    - Coerces everything into FieldWithConfidence objects (assigning default
      confidence when missing) while clamping to configured bounds.
"""

from typing import Dict, Any
from app.core.config import get_settings
from app.extraction.vision_model_client import RawExtraction
from app.extraction.schemas import FlatExtractionResult, FieldWithConfidence

settings = get_settings()

def normalize(raw: RawExtraction) -> FlatExtractionResult:
    """Return normalized FlatExtractionResult from a RawExtraction instance.

    Each raw value is passed through FieldWithConfidence.from_any so plain
    scalars, already-wrapped dicts, or FieldWithConfidence objects converge to
    a single canonical representation.
    """
    def wrap_map(src: Dict[str, Any]) -> Dict[str, FieldWithConfidence]:
        out: Dict[str, FieldWithConfidence] = {}
        for k, v in (src or {}).items():
            fc = FieldWithConfidence.from_any(
                v,
                default_conf=settings.DEFAULT_CONFIDENCE,
                lo=settings.MIN_CONFIDENCE,
                hi=settings.MAX_CONFIDENCE,
            )
            out[k] = fc
        return out

    return FlatExtractionResult(
        doc_type=raw.doc_type,
        fields=wrap_map(raw.fields),
        extra_fields=wrap_map(raw.extra_fields),
    )