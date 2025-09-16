"""Multi-page / multi-document extraction orchestration.

This module contains the higher-level logic for turning a PDF (or other multi-page
container) into a set of logically grouped documents. Each *document* is a group of
consecutive pages that the model (and smoothing heuristics) agree share a document
type (doc_type). We then merge the fields within each group so the client receives a
concise record per logical document, along with meta statistics for monitoring.

Design goals:
    * Keep page-level extraction independent (enables concurrency and future retry).
    * Heuristic smoothing kept explicit and data-driven (easy to disable / tune).
    * Preserve FIRST non-empty field value across pages to reduce overwrite noise.
    * Do not delete or mutate original per‑page results (functional purity aside from
        merging) – we can always revisit richer provenance if required.
    * Minimize coupling with single-document path: only shared piece is prompt schema.

Future extensions (documented, not implemented here to keep scope tight):
    * Confidence aggregation: min / mean / geometric mean across page confidences.
    * Layout-aware continuation detection (e.g., using y-coordinate distributions).
    * Adaptive regrouping using clustering on embedding vectors of page text.
    * Spill detection: if a page introduces many novel keys, split even if doc_type equals.

All existing logic intentionally left unmodified; only commentary added per request.
"""

import time                      # timing to measure total extraction latency
import asyncio                   # run page extraction concurrently
from typing import List, Optional, Dict, Tuple, Set, Union
import logging                   # lightweight structured logging

from app.multidoc.page_loader import file_bytes_to_pages
from app.multidoc.multi_schemas import (
    MultiExtractionResult,
    MultiExtractionMeta,
    MultiPageDoc,
)
from app.extraction.schemas import FlatExtractionResult, CanonicalFields
from app.extraction.prompts import build_prompt
from app.extraction.vision_model_client import vision_extractor
from app.extraction.norm_helper import normalize as normalize_raw
from app.extraction.schemas import FieldWithConfidence
from app.core.config import get_settings

logger = logging.getLogger("kyc.extract")  # module-level logger
settings = get_settings()  # initialize configuration for DEFAULT_CONFIDENCE usage

# =============================
# Heuristic configuration knobs
# =============================
# These control how we "repair" missing doc_type values on continuation pages.
# Keeping them at top makes tuning easy without diving into logic.
FORWARD_FILL = True                  # If a page has no doc_type but prior page did, try inheriting it.
BRIDGE_GAP = True                    # If pattern is A, None, A -> fill the middle with A.
MIN_FIELDS_FOR_NEW_DOC = 3           # Large number of novel keys on a None page => likely a new document.
MIN_KEY_OVERLAP_FOR_CONTINUATION = 1 # Minimum repeated keys to consider the page a continuation.

"""# Tuning guidance:
#   - Increase MIN_FIELDS_FOR_NEW_DOC if documents often share only a handful of keys.
#   - Increase MIN_KEY_OVERLAP_FOR_CONTINUATION to be stricter about joining pages.
#   - Disable FORWARD_FILL when doc_type hallucinations cause cascading errors.
#   - Disable BRIDGE_GAP if single stray pages should remain isolated for auditing.
"""

def _merge_field_sets(results: List[FlatExtractionResult]) -> Tuple[Dict[str, FieldWithConfidence], Dict[str, FieldWithConfidence]]:
    """Merge core + extra field dictionaries across pages in one grouped document.

    Strategy: "first non-empty wins" – we intentionally do NOT overwrite an earlier
    value with a later one to avoid drift from front-page canonical entries.
    """
    merged_fields: Dict[str, FieldWithConfidence] = {}
    merged_extra: Dict[str, FieldWithConfidence] = {}

    def merge(dest: Dict[str, FieldWithConfidence], src: Dict[str, Union[str, FieldWithConfidence]]):
        for k, v in src.items():
            if not v:
                continue
            if k not in dest:
                if isinstance(v, FieldWithConfidence):
                    dest[k] = v
                else:
                    dest[k] = FieldWithConfidence(value=v, confidence=settings.DEFAULT_CONFIDENCE)

    for r in results:
        merge(merged_fields, r.fields)
        merge(merged_extra, r.extra_fields)
    return merged_fields, merged_extra



def _group_consecutive(types: List[Optional[str]]) -> List[List[int]]:
    """Group consecutive pages that share the same (already smoothed) doc_type.

    The smoothed list may still contain None values; consecutive Nones become their
    own group so the client can inspect ambiguous sequences separately.
    """
    groups: List[List[int]] = []
    current: List[int] = []
    prev = None
    for idx, dt in enumerate(types):
        if prev is None:
            current = [idx]            # start first group
        elif dt == prev:
            current.append(idx)        # continue current group
        else:
            groups.append(current)     # close previous group
            current = [idx]            # start new group
        prev = dt
    if current:
        groups.append(current)         # append last open group
    return groups


def _flatten_value(v):
    """Normalize any model-returned value (various shapes) into a plain string.

    Accepted shapes / handling policy:
      * dict -> attempt canonical keys ('value', 'VALUE', 'val'); fallback to first scalar.
      * list/tuple -> join stringified non-None members with a single space.
      * scalar -> stringify.
      * None -> empty string (filtered later).

    Confidence is intentionally ignored here; multi-page confidence aggregation has
    not yet been standardized (see module docstring Future extensions).
    """
    if isinstance(v, dict):
        # Preferred explicit value keys
        for key in ("value", "VALUE", "val"):
            if key in v and v[key] is not None:
                return str(v[key])
        # Fallback: first scalar entry
        for _, v2 in v.items():
            if isinstance(v2, (str, int, float)):
                return str(v2)
        return ""
    if isinstance(v, (list, tuple)):
        return " ".join(str(x) for x in v if x is not None)
    if v is None:
        return ""
    return str(v)

# def _normalize_field_map(raw: Dict[str, object]) -> Dict[str,str]:
    # """Apply _flatten_value to each raw field; drop empty results.

    # Guarantees downstream code always sees Dict[str, str].
    # """
    # out: Dict[str,str] = {}
    # for k, v in (raw or {}).items():
    #     fv = _flatten_value(v)
    #     if fv:
    #         out[k] = fv
    # return out

async def _extract_page(page_bytes: bytes, allowed_keys: List[str]) -> FlatExtractionResult:
    """Run model inference for a single page image and normalize output.

    Notes
    -----
    * allowed_keys ensures the prompt enumerates the canonical schema.
    * Confidence is NOW captured via a hidden '_normalized' attribute (FlatExtractionResult with FieldWithConfidence maps).
    * Any exceptions bubble up to gather(); caller converts to placeholder record.
    """
    prompt = build_prompt(doc_type=None, allowed_keys=allowed_keys)
    res = await vision_extractor.run(prompt, [page_bytes])
    raw = res.get("raw")
    doc_type = getattr(raw, "doc_type", None)
    fields_raw = getattr(raw, "fields", {}) or {}
    extra_raw = getattr(raw, "extra_fields", {}) or {}
    # fields = _normalize_field_map(fields_raw)
    # extra = _normalize_field_map(extra_raw)
    fields = {k: FieldWithConfidence(value=v.get("value"), confidence=v.get("confidence", settings.DEFAULT_CONFIDENCE))
          for k, v in fields_raw.items()}
    extra = {k: FieldWithConfidence(value=v.get("value"), confidence=v.get("confidence", settings.DEFAULT_CONFIDENCE))
         for k, v in extra_raw.items()}
    return FlatExtractionResult(doc_type=doc_type, fields=fields, extra_fields=extra)

def _smooth_doc_types(results: List[FlatExtractionResult]) -> List[Optional[str]]:
    """Repair missing doc_type values using heuristic rules.

    Steps
    -----
     1. Collect raw doc_type list.
     2. FORWARD_FILL: if enabled, copy forward last observed type when a page
         appears lightweight or shares enough keys with the previous.
     3. BRIDGE_GAP: fill single-page gaps A · A -> A A A (dot represents None).

    Returns
    -------
    List[Optional[str]]: New list (same length) with inferred types filled.
    """
    types = [r.doc_type for r in results]
    if not (FORWARD_FILL or BRIDGE_GAP):
        return types

    # Pre-compute key sets for overlap checks (union of fields + extra)
    page_key_sets: List[Set[str]] = [set(r.fields.keys()) | set(r.extra_fields.keys()) for r in results]
    out = types[:]

    if FORWARD_FILL:
        last_type = None
        last_keys: Set[str] = set()
        for i, t in enumerate(out):
            if t:  # observed type anchors the continuation chain
                last_type = t
                last_keys = page_key_sets[i]
            else:
                if last_type:
                    overlap = len(page_key_sets[i] & last_keys)
                    # continuation if: few total keys OR overlapping keys exceed threshold
                    if (len(page_key_sets[i]) < MIN_FIELDS_FOR_NEW_DOC or
                        overlap >= MIN_KEY_OVERLAP_FOR_CONTINUATION):
                        out[i] = last_type
                        # keep last_keys from anchor page (avoids drift)

    if BRIDGE_GAP:
        # Identify simple sandwich pattern: A, None, A
        for i in range(1, len(out) - 1):
            if not types[i] and out[i - 1] and out[i + 1] == out[i - 1]:
                out[i] = out[i - 1]

    return out


async def extract_multi_document(filename: str, file_bytes: bytes) -> MultiExtractionResult:
    """High-level orchestration for multi-page / multi-document extraction.

        Pipeline
        --------
            1. Rasterize input into page images (delegated to page_loader/file_bytes_to_pages).
            2. Launch concurrent page-level extractions for latency reduction.
            3. Apply doc_type smoothing heuristics (forward fill + bridge gap).
            4. Group consecutive pages with the same (possibly inferred) doc_type.
            5. Merge fields within each group using first-win semantics.
            6. Return structured MultiExtractionResult plus meta timing + counts.
        """
    start = time.time()
    pages = file_bytes_to_pages(filename, file_bytes)
    allowed_keys = list(CanonicalFields.model_fields.keys())  # canonical schema keys

    # Fire off page-level extractions concurrently for speed.
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

    # Step 3: repair doc_type continuity
    smoothed_types = _smooth_doc_types(safe_results)
    # Step 4: group pages
    groups = _group_consecutive(smoothed_types)

    # Step 5: merge fields per group
    docs: List[MultiPageDoc] = []
    for gid, g in enumerate(groups):
        segment = [safe_results[i] for i in g]
        doc_type = smoothed_types[g[0]] or next((s.doc_type for s in segment if s.doc_type), None)
        merged_fields, merged_extra = _merge_field_sets(segment)
        # representative = segment[0]
        # representative intentionally omitted from output per simplified schema requirement
        

        # # For fast check of which keys already assigned
        # assigned_core = set()
        # assigned_extra = set()

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

    # Meta metrics: helpful for monitoring performance and grouping behavior
    meta = MultiExtractionMeta(
        total_pages=len(pages),
        total_groups=len(docs),
        elapsed_ms=int((time.time() - start) * 1000),
    )
    return MultiExtractionResult(documents=docs, meta=meta)

