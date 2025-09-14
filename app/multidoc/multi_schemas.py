from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from app.extraction.schemas import FlatExtractionResult

class MultiPageDoc(BaseModel):  # Represents one grouped logical document
    group_id: int
    doc_type: Optional[str] = None
    page_indices: List[int]
    merged_fields: Dict[str, str] = Field(default_factory=dict)
    merged_extra_fields: Dict[str, str] = Field(default_factory=dict)
    # merged_fields_confidence: Dict[str, float] = Field(default_factory=dict)
    # merged_extra_fields_confidence: Dict[str, float] = Field(default_factory=dict)
    # representative: FlatExtractionResult

class MultiExtractionMeta(BaseModel):  # high-level stats for response
    total_pages: int
    total_groups: int
    elapsed_ms: int

class MultiExtractionResult(BaseModel):  # top-level multi-doc payload
    documents: List[MultiPageDoc]
    meta: MultiExtractionMeta
