"""Pydantic models for multi-document extraction responses.

These are intentionally minimal: the single-document pathway already defines
confidence-bearing structures. For multi-document we presently aggregate ONLY
string field values (first-non-empty per group). Confidence aggregation strategies
are noted but deferred to avoid premature complexity.

Backward compatibility considerations:
    * Adding new optional fields in these models is safe (Pydantic tolerant parsing).
    * Renaming existing keys would be a breaking change – avoid without versioning.

Potential future fields (commented out in MultiPageDoc):
    * merged_fields_confidence / merged_extra_fields_confidence (dict[str,float])
    * representative: a Page-level FlatExtractionResult for provenance debugging.
"""

from typing import List, Optional, Dict
from pydantic import BaseModel, Field
# from app.extraction.schemas import FlatExtractionResult
from app.extraction.schemas import FieldWithConfidence  # Added: for rich value+confidence objects

class MultiPageDoc(BaseModel):  # Represents one grouped logical document
    group_id: int
    doc_type: Optional[str] = None
    page_indices: List[int]
    merged_fields: Dict[str, FieldWithConfidence] = Field(default_factory=dict)
    merged_extra_fields: Dict[str, FieldWithConfidence] = Field(default_factory=dict)
    # merged_fields_confidence: Dict[str, float] = Field(default_factory=dict)
    # merged_extra_fields_confidence: Dict[str, float] = Field(default_factory=dict)
    # representative: FlatExtractionResult
    
    # Convenience property (does not remove existing keys) to yield the API-like flat shape you want
    def as_flat_result(self) -> Dict[str, dict]:
        return {
            "doc_type": self.doc_type,
            "fields": {k: v.model_dump() for k, v in self.fields_objects.items()},
            "extra_fields": {k: v.model_dump() for k, v in self.extra_fields_objects.items()},
        }
    
class MultiExtractionMeta(BaseModel):  # High-level stats for response (monitoring)
    total_pages: int
    total_groups: int
    elapsed_ms: int

class MultiExtractionResult(BaseModel):  # Top-level multi-doc payload returned by endpoint
    documents: List[MultiPageDoc]
    meta: MultiExtractionMeta
