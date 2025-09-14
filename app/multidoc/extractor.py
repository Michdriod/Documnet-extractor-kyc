import time
import asyncio
from typing import List, Optional, Dict, Tuple, Set
import logging

from app.multidoc.page_loader import file_bytes_to_pages
from app.multidoc.multi_schemas import (
    MultiExtractionResult,
    MultiExtractionMeta,
    MultiPageDoc,
)
from app.extraction.schemas import FlatExtractionResult, CanonicalFields
from app.extraction.prompts import build_prompt
from app.extraction.vision_model_client import vision_extractor

logger = logging.getLogger("kyc.extract")

# Heuristic controls (tunable / could move to settings later)
FORWARD_FILL = True                 # propagate previous non-null doc_type
BRIDGE_GAP = True                   # bridge A, None, A pattern
MIN_FIELDS_FOR_NEW_DOC = 3          # if a None page has this many distinct keys and little overlap, consider new doc
MIN_KEY_OVERLAP_FOR_CONTINUATION = 1  # at least this many repeated keys means continuation


def _merge_field_sets(results: List[FlatExtractionResult]) -> Tuple[Dict[str,str], Dict[str,str]]:
    """Merge string field maps; first non-empty wins (simple)."""
    merged_fields: Dict[str, str] = {}
    merged_extra: Dict[str, str] = {}

    def merge(dest: Dict[str,str], src: Dict[str,str]):
        for k, v in src.items():
            if not v:
                continue
            if k not in dest:
                dest[k] = v

    for r in results:
        merge(merged_fields, r.fields)
        merge(merged_extra, r.extra_fields)
    return merged_fields, merged_extra


def _group_consecutive(types: List[Optional[str]]) -> List[List[int]]:
    groups: List[List[int]] = []
    current: List[int] = []
    prev = None
    for idx, dt in enumerate(types):
        if prev is None:
            current = [idx]
        elif dt == prev:
            current.append(idx)
        else:
            groups.append(current)
            current = [idx]
        prev = dt
    if current:
        groups.append(current)
    return groups


def _flatten_value(v):
    if isinstance(v, dict):
        # Expect nested {'value':..., 'confidence':...}
        for key in ("value", "VALUE", "val"):
            if key in v and v[key] is not None:
                return str(v[key])
        # Fallback: first non-null scalar
        for k2, v2 in v.items():
            if isinstance(v2, (str, int, float)):
                return str(v2)
        return ""
    if isinstance(v, (list, tuple)):
        return " ".join(str(x) for x in v if x is not None)
    if v is None:
        return ""
    return str(v)

def _normalize_field_map(raw: Dict[str, object]) -> Dict[str,str]:
    out: Dict[str,str] = {}
    for k, v in (raw or {}).items():
        fv = _flatten_value(v)
        if fv:
            out[k] = fv
    return out

async def _extract_page(page_bytes: bytes, allowed_keys: List[str]) -> FlatExtractionResult:
    prompt = build_prompt(doc_type=None, allowed_keys=allowed_keys)
    res = await vision_extractor.run(prompt, [page_bytes])
    raw = res.get("raw")
    doc_type = getattr(raw, "doc_type", None)
    fields_raw = getattr(raw, "fields", {}) or {}
    extra_raw = getattr(raw, "extra_fields", {}) or {}
    fields = _normalize_field_map(fields_raw)
    extra = _normalize_field_map(extra_raw)
    return FlatExtractionResult(doc_type=doc_type, fields=fields, extra_fields=extra)


def _smooth_doc_types(results: List[FlatExtractionResult]) -> List[Optional[str]]:
    types = [r.doc_type for r in results]
    if not (FORWARD_FILL or BRIDGE_GAP):
        return types

    page_key_sets: List[Set[str]] = [set(r.fields.keys()) | set(r.extra_fields.keys()) for r in results]
    out = types[:]

    if FORWARD_FILL:
        last_type = None
        last_keys: Set[str] = set()
        for i, t in enumerate(out):
            if t:
                last_type = t
                last_keys = page_key_sets[i]
            else:
                if last_type:
                    overlap = len(page_key_sets[i] & last_keys)
                    # continuation if few keys OR overlap
                    if len(page_key_sets[i]) < MIN_FIELDS_FOR_NEW_DOC or overlap >= MIN_KEY_OVERLAP_FOR_CONTINUATION:
                        out[i] = last_type
                        # don't update last_keys (keeps anchor)

    if BRIDGE_GAP:
        # A, None, A pattern
        for i in range(1, len(out) - 1):
            if not types[i] and out[i - 1] and out[i + 1] == out[i - 1]:
                out[i] = out[i - 1]

    return out


async def extract_multi_document(filename: str, file_bytes: bytes) -> MultiExtractionResult:
    start = time.time()
    pages = file_bytes_to_pages(filename, file_bytes)
    allowed_keys = list(CanonicalFields.model_fields.keys())
    tasks = [asyncio.create_task(_extract_page(pb, allowed_keys)) for pb in pages]
    page_results = await asyncio.gather(*tasks, return_exceptions=True)

    safe_results: List[FlatExtractionResult] = []
    types: List[Optional[str]] = []
    for idx, r in enumerate(page_results):
        if isinstance(r, Exception):
            logger.warning("multi_page_extraction_error page=%d error=%s", idx, r)
            safe_results.append(FlatExtractionResult(doc_type=None, fields={}, extra_fields={}))
            types.append(None)
        else:
            safe_results.append(r)
            types.append(r.doc_type)

    # Smooth doc types first to keep continuation pages together
    smoothed_types = _smooth_doc_types(safe_results)
    groups = _group_consecutive(smoothed_types)

    docs: List[MultiPageDoc] = []
    for gid, g in enumerate(groups):
        segment = [safe_results[i] for i in g]
        doc_type = smoothed_types[g[0]] or next((s.doc_type for s in segment if s.doc_type), None)
        merged_fields, merged_extra = _merge_field_sets(segment)
        representative = segment[0]
        docs.append(
            MultiPageDoc(
                group_id=gid,
                doc_type=doc_type,
                page_indices=g,
                merged_fields=merged_fields,
                merged_extra_fields=merged_extra,
                # merged_fields_confidence={},
                # merged_extra_fields_confidence={},
                # representative=representative,
            )
        )

    meta = MultiExtractionMeta(
        total_pages=len(pages),
        total_groups=len(docs),
        elapsed_ms=int((time.time() - start) * 1000),
    )
    return MultiExtractionResult(documents=docs, meta=meta)
