# KYC / ID Document Extraction Service

FastAPI service for structured extraction from KYC / identity / supporting documents (passports, national IDs, driver licenses, utility bills, land & property docs, permits, visas, statements, etc.).

Core capabilities:

- Batch single‑document extraction (one request, many files OR many URLs) – always returns a list.
- Multi‑document grouping from a multi‑page PDF or composite image (`/extract/vision/multi`).
- Large canonical field superset + automatic fallback to `extra_fields` for anything unmapped.
- Confidence scoring per field (object form) with configurable strictness.
- First‑win merge semantics across multi‑page groups (no confidence averaging yet).
- Explicit anti‑hallucination + completeness prompt strategy (canonical priority + per‑page isolation).

---
## 1. Quick Start

```bash
# (optional) create & activate virtualenv
python -m venv docvenv
source docvenv/bin/activate

pip install -r requirements.txt

# Run API (adjust host/port as needed)
uvicorn mains:app --reload --port 8000
```

Then open <http://localhost:8000/docs> for Swagger UI.

---
## 2. Feature Overview

| Capability | Current Behavior |
|------------|------------------|
| Batch single extraction | Multiple uploaded files (`files[]`) OR multiple URLs (`source_urls[]`) OR exactly one legacy `file` OR one `source_url`. Always returns `List[FlatExtractionResult]` (single input => length 1). |
| Multi extraction | One multi‑page PDF / image -> groups consecutive pages into logical documents. |
| Vision model wrapper | Single vision model (config `VISION_MODEL`) invoked once per page; concurrency via `asyncio.gather`. |
| Canonical schema | Broad optional field superset (`CanonicalFields`). Only visibly present values appear. |
| Extra fields | Unmapped but useful values placed under `extra_fields` / `merged_extra_fields` (snake_case keys). |
| Confidence | Per field object: `{ "value": str, "confidence": float }` (0–1, clamped). Can allow plain strings if `REQUIRE_CONFIDENCE=0` (not default). |
| Prompt strategy | Single consolidated system prompt: canonical priority (must use canonical key if meaning matches), completeness, per‑page isolation, no fabrication. Low‑cap guidance ALWAYS appended. |
| Multi-page merge | First non‑empty value wins; no overwrites, no confidence averaging yet. |
| Heuristics | Doc type smoothing: forward fill + bridge gap + key overlap thresholds. |
| Logging | Debug metrics & prompt length when `DEBUG_EXTRACTION=1`. |
| Error surfaces | Structured error envelopes or simple `detail` codes (see Section 11). |

---
## 3. High Level Flow

1. Receive file(s) or URL(s)
2. Validate size & extension
3. (PDF) Rasterize limited pages (single) or extended pages (multi)
4. Build system prompt (enumerates canonical keys, anti‑hallucination rules)
5. Run vision model per page concurrently
6. Normalize raw model output into `FieldWithConfidence` objects.
7. (Multi) Smooth doc types, group consecutive pages, first‑win merge field maps.
8. Return JSON list (single) or grouped structure (multi).

---
## 4. Key Files

| File | Purpose |
|------|---------|
| `app/api/routes.py` | Batch-capable single document endpoint |
| `app/api/routes_multi.py` | Multi‑document grouping endpoint |
| `app/extraction/processing.py` | Validation, PDF render & basic image handling |
| `app/extraction/prompts.py` | Consolidated system prompt builder |
| `app/extraction/vision_model_client.py` | Vision model wrapper |
| `app/extraction/schemas.py` | Canonical + output models (FieldWithConfidence etc.) |
| `app/extraction/norm_helper.py` | Raw → normalized structure conversion |
| `app/multidoc/page_loader.py` | Rasterize pages for multi extraction |
| `app/multidoc/extractor.py` | Multi-page extraction + grouping heuristics + merging |
| `app/multidoc/multi_schemas.py` | Multi extraction response models |
| `app/core/config.py` | Environment/config switches |
| `frontend/` | Simple JS frontend demo (multi vs single modes) |

---
## 5. Configuration (Environment Variables)

| Var | Default | Meaning |
|-----|---------|---------|
| `GROQ_API_KEY` | (required) | API key for vision provider (Groq example) |
| `VISION_MODEL` | gemma3:4b | Vision-capable model identifier |
| `MAX_FILE_MB` | 15 | Upload size cap (MB) |
| `MAX_PAGES_RENDER` | 4 | Max PDF pages in single endpoint |
| `MULTI_MAX_PAGES` | 40 | Max pages processed in multi endpoint |
| `DEBUG_EXTRACTION` | 1 | Enable verbose logs (1 / 0) |
| `REQUIRE_CONFIDENCE` | 1 | Enforce object form with confidence (else strings allowed) |
| `DEFAULT_CONFIDENCE` | 0.50 | Fallback when model omits confidence |

Set before launch, e.g.:

```bash
export GROQ_API_KEY=sk_your_key
export VISION_MODEL=gemma3:4b
```

---
## 6. API Reference

### 6.1 Single Document Endpoint (Batch Capable)
`POST /extract/vision/single`

Exactly one of these source variants must be provided:

1. Multiple upload files: `files[]` (multipart, 1..N)
2. Single legacy file: `file`
3. Single remote URL: `source_url`
4. Multiple remote URLs: repeated `source_urls[]`

Optional: `doc_type` (hint; model may still infer per page).

Response: ALWAYS a JSON array of `FlatExtractionResult` objects.

Field shape (each result):
```json
{
  "doc_type": "passport",
  "fields": {
    "surname": {"value": "DOE", "confidence": 0.94},
    "passport_number": {"value": "A1234567", "confidence": 0.91}
  },
  "extra_fields": {
    "place_of_issue": {"value": "ABUJA", "confidence": 0.88}
  }
}
```

Example (multiple files):
```bash
curl -X POST http://localhost:8000/extract/vision/single \
  -F files=@samples/passport_p1.jpg \
  -F files=@samples/passport_p2.jpg
```

Example (multiple URLs):
```bash
curl -X POST http://localhost:8000/extract/vision/single \
  -F source_urls=https://example.com/doc1.jpg \
  -F source_urls=https://example.com/doc2.jpg
```

### 6.2 Multi Document Endpoint
`POST /extract/vision/multi`

Parameters (Form / Multipart): choose exactly one:

- `file`  (multi-page PDF or composite image)
- `source_url`
- `file_path` (server‑local path; internal/trusted only)

Response (simplified – confidence objects retained):
```json
{
	"documents": [
		{
			"group_id": 0,
			"doc_type": "passport",
			"page_indices": [0, 1],
			"merged_fields": {"surname": {"value": "DOE", "confidence": 0.93}},
			"merged_extra_fields": {"issuing_authority": {"value": "IMMIGRATION", "confidence": 0.90}}
		},
		{
			"group_id": 1,
			"doc_type": "driver_license",
			"page_indices": [2],
			"merged_fields": {"license_number": {"value": "DL-77821", "confidence": 0.89}},
			"merged_extra_fields": {}
		}
	],
	"meta": {"total_pages": 3, "total_groups": 2, "elapsed_ms": 945}
}
```

Example:
```bash
curl -X POST http://localhost:8000/extract/vision/multi \
  -F file=@samples/mixed_docs.pdf
```

---
## 7. Multi Page Grouping Heuristics

When a document spans multiple pages some pages may miss `doc_type`. We repair it:

| Heuristic | What it does | Analogy |
|-----------|--------------|---------|
| `FORWARD_FILL` | Copy previous doc type to an unlabeled page if it looks like a continuation | Chapter title missing but story continues |
| `BRIDGE_GAP` | Pattern A, None, A → fill middle with A | Sandwich: same bread, missing label in middle |
| `MIN_FIELDS_FOR_NEW_DOC` | Many new keys on unlabeled page → treat as new document | Suddenly new form layout |
| `MIN_KEY_OVERLAP_FOR_CONTINUATION` | Shared keys with previous page → continuation | Same section heading reused |

Constants (top of `app/multidoc/extractor.py`):

| Constant | Default | Effect |
|----------|---------|--------|
| `FORWARD_FILL` | True | Inherit prior doc_type for plausible continuation pages. |
| `BRIDGE_GAP` | True | Fill single None gaps: A · A -> A A A. |
| `MIN_FIELDS_FOR_NEW_DOC` | 3 | If unlabeled page introduces >= this many novel keys → new doc. |
| `MIN_KEY_OVERLAP_FOR_CONTINUATION` | 1 | Minimum overlapping keys to treat as continuation. |

Merging: first non‑empty value wins (prevents later noisy overwrites). Future: confidence aggregation / provenance lists.

---
## 8. Canonical vs Extra Fields

Canonical fields: large superset (see `CanonicalFields` model). Only populated if visibly present. Everything else goes to `extra_fields` (single) or `merged_extra_fields` (multi).

Adding new canonical keys: edit `CanonicalFields`; restart – they automatically appear in the allowed prompt list.

---
## 9. Normalization Summary

Current normalization (see `norm_helper.py`):

- Wrap every field (canonical + extra) into `FieldWithConfidence` (clamping confidence to [0,1]).
- If model omits confidence, fallback to `DEFAULT_CONFIDENCE`.
- No format rewriting: dates, numbers, MRZ, and IDs are preserved EXACTLY as produced by the model (the prompt instructs original formatting retention). Earlier design ideas for date normalization (YYYY-MM-DD) are intentionally not active.
- Future (planned): MRZ cleanup, date canonicalization toggle, ID whitespace normalization.

---
## 10. Logging & Debug

With `DEBUG_EXTRACTION=1` you may see:
- Prompt length + doc_type hints
- Page counts & byte sizes
- Model latency metrics
- Multi grouping stats (groups, total pages)

---
## 11. Troubleshooting & Error Codes

| Symptom / Code | Likely Cause | Fix |
|----------------|-------------|-----|
| Empty `fields` | Model uncertain / low contrast image | Improve scan, enable debug, inspect prompt size |
| Missing back page grouping | Heuristics too strict | Adjust `MIN_FIELDS_FOR_NEW_DOC` / `MIN_KEY_OVERLAP_FOR_CONTINUATION` |
| Unexpected new group | False split | Inspect overlapping keys; relax heuristics |
| PDF pages cut off (single) | Over page cap | Raise `MAX_PAGES_RENDER` or use multi endpoint |
| `url_too_large` | Remote file exceeded size limit | Increase `MAX_FILE_MB` if safe |
| `model_inference_error` | Upstream call failed | Verify model name/connectivity |
| `provide_exactly_one_source_variant` | Multiple source variants in single endpoint | Send only one of files/file/source_url/source_urls |
| `provide_exactly_one_source` | Multiple inputs in multi endpoint | Supply exactly one of file/source_url/file_path |
| `pdf_support_requires_pymupdf` | PyMuPDF missing | Install dependency |
| `url_fetch_error` | Network / non-200 response | Validate URL / availability |
| `invalid_url_scheme` | Non-http/https URL | Use valid scheme |
| `internal_error` | Unexpected server exception | Check logs (stack trace recorded) |

---
## 12. Adding a New Canonical Field

1. Add optional attribute to `CanonicalFields`.
2. Restart server.
3. New key appears in prompt allowing direct extraction.

---
## 13. Security Notes

- Restrict or remove `file_path` in production.
- Add authentication / authorization (not included yet).
- Enforce MIME checks if hardening.
- Consider temporary sanitized storage if persistence layer added.

---
## 14. Performance Notes

- Page model calls run concurrently (`asyncio.gather`).
- Rasterization DPI tuned for balance; increase cautiously for tiny fonts.
- First‑win merge avoids O(N^2) overwrites.

---
## 15. Roadmap / Future Enhancements

- Confidence aggregation across grouped pages
- Optional OCR fallback for low-confidence pages
- Auto redaction / masking (PII control)
- Caching of repeated pages (hash based)
- Batch async ingestion queue
- Structured template hints per doc_type
- Date / MRZ / ID post-normalizers (feature flag)
- Temperature & model-level settings abstraction

---
## 16. Example Minimal Integration (Python)

```python
import requests

with open("sample/passport.jpg", "rb") as f:
    r = requests.post("http://localhost:8000/extract/vision/single", files={"file": f})
print(r.json())
```

---
## 17. License

Add your chosen license (MIT, Apache-2.0, etc.).

---
## 18. Prompt Strategy (At a Glance)

Key enforced rules (abridged):

1. Extract ONLY visually present text (no speculation).
2. MUST use a canonical key if the value fits (canonical priority 3a).
3. Per‑page isolation: never borrow from previous pages.
4. Completeness: capture every clearly legible field (canonical or extra).
5. Dates & IDs: keep original formatting (no normalization).
6. Confidence: realistic 0–1; omit field instead of fabricating unreadable text.
7. Output contract: `doc_type`, `fields`, `extra_fields` only. Valid JSON.

Low‑cap guidance (stepwise instructions) is always appended for consistency across model sizes.

---
## 19. Summary

Foundation for reliable, explainable KYC parsing: unified prompt, broad schema, batching, multi-page grouping, and confidence-rich field objects. Extension points: heuristics tuning, normalization layers, model switching, and aggregation logic.

> Tune heuristics empirically—avoid premature complexity.

