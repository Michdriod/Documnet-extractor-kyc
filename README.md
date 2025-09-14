# KYC / ID Document Extraction Service (Phase 1)

Simple FastAPI service that extracts structured fields from KYC / identity / supporting documents (passport, national ID, driver license, utility bill, land documents, etc.).

Supports:

- Single document extraction (`/extract/vision/single`)
- Multi‑document PDF or image bundle extraction (`/extract/vision/multi`) with smart page grouping

The model is called once per page (vision LLM) and the backend merges and normalizes results.

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
## 2. Features

| Capability | Description |
|------------|-------------|
| Single extraction | Pass one file OR a remote URL (PDF / image) |
| Multi extraction | Pass a multi‑page PDF or an image set; groups pages into logical documents |
| Vision model client | Groq model usage (no fallback) via unified wrapper |
| Canonical field schema | Large optional superset; only filled fields are returned |
| Extra fields | Non‑canonical values returned under `extra_fields` (multi endpoint merges them) |
| Page rendering | PyMuPDF rasterization with size caps (fast, memory‑safe) |
| Normalization | Dates, MRZ, ID formats cleaned; confidence scoring infra (minimal in output) |
| Heuristics | Continuation page smoothing to avoid splitting one document across groups |
| Logging | Toggle detailed debug via `DEBUG_EXTRACTION` |

---
## 3. High Level Flow

1. Receive file or URL
2. Validate size & extension
3. (PDF) Rasterize limited pages (single) or extended pages (multi)
4. Build single system prompt (no user prompt message)
5. Run vision model per page
6. Normalize fields (flatten values → plain strings)
7. (Multi) Smooth doc types, group, merge fields
8. Return JSON

---
## 4. Key Files

| File | Purpose |
|------|---------|
| `app/api/routes.py` | Single document endpoint logic |
| `app/api/routes_multi.py` | Multi‑document endpoint |
| `app/extraction/processing.py` | Validation, PDF render, normalization helpers |
| `app/extraction/prompts.py` | System prompt builder |
| `app/extraction/vision_model_client.py` | Model wrapper (Groq) |
| `app/extraction/schemas.py` | Canonical + output models |
| `app/multidoc/page_loader.py` | Page extraction for multi use case |
| `app/multidoc/extractor.py` | Multi-page extraction + grouping heuristics |
| `app/multidoc/multi_schemas.py` | Multi extraction response models |
| `app/core/config.py` | Environment/config switches |

---
## 5. Configuration (Environment Variables)

| Var | Default | Meaning |
|-----|---------|---------|
| `GROQ_API_KEY` | (required) | API key for Groq model |
| `VISION_MODEL` | meta-llama/llama-4-scout-17b-16e-instruct | Model name |
| `MAX_FILE_MB` | 15 | Upload size cap (MB) |
| `MAX_PAGES_RENDER` | 4 | Max PDF pages in single endpoint |
| `MULTI_MAX_PAGES` | 40 | Max pages processed in multi endpoint |
| `DEBUG_EXTRACTION` | 1 | Enable verbose logs (1 / 0) |

Set before launch, e.g.:

```bash
export GROQ_API_KEY=sk_your_key
export VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
```

---
## 6. API Reference

### 6.1 Single Document Endpoint
`POST /extract/vision/single`

Parameters (Form / Multipart):

- `file` (one PDF or image) OR `source_url` (exactly one)
- `doc_type` (optional hint – may be ignored if model infers)

Response Body (simplified):

```json
{
	"doc_type": "passport",
	"fields": {"surname": "DOE", "passport_number": "A1234567"},
	"extra_fields": {"place_of_issue": "ABUJA"}
}
```

Example curl:

```bash
curl -X POST http://localhost:8000/extract/vision/single \
	-F file=@sample/passport_page1.jpg
```

### 6.2 Multi Document Endpoint
`POST /extract/vision/multi`

Parameters (Form / Multipart): choose exactly one:

- `file`  (multi-page PDF or composite image)
- `source_url`
- `file_path` (server‑local path; use carefully)

Response (simplified):

```json
{
	"documents": [
		{
			"group_id": 0,
			"doc_type": "passport",
			"page_indices": [0, 1],
			"merged_fields": {"surname": "DOE"},
			"merged_extra_fields": {"issuing_authority": "IMMIGRATION"}
		},
		{
			"group_id": 1,
			"doc_type": "driver_license",
			"page_indices": [2],
			"merged_fields": {"license_number": "DL-77821"},
			"merged_extra_fields": {}
		}
	],
	"meta": {"total_pages": 3, "total_groups": 2, "elapsed_ms": 945}
}
```

Example curl:

```bash
curl -X POST http://localhost:8000/extract/vision/multi \
	-F file=@samples/mixed_docs.pdf
```

---
## 7. Multi Page Grouping Heuristics (Simple Explanation)

When a document spans multiple pages (front/back, continuation clauses), some pages may miss `doc_type`. We repair it:

| Heuristic | What it does | Analogy |
|-----------|--------------|---------|
| `FORWARD_FILL` | Copy previous doc type to an unlabeled page if it looks like a continuation | Chapter title missing but story continues |
| `BRIDGE_GAP` | Pattern A, None, A → fill middle with A | Sandwich: same bread, missing label in middle |
| `MIN_FIELDS_FOR_NEW_DOC` | Many new keys on unlabeled page → treat as new document | Suddenly new form layout |
| `MIN_KEY_OVERLAP_FOR_CONTINUATION` | Shared keys with previous page → continuation | Same section heading reused |

Tuning lives at the top of `app/multidoc/extractor.py`.

---
## 8. Canonical vs Extra Fields

Canonical fields: large superset (see `CanonicalFields` model). Only populated if visibly present. Everything else goes to `extra_fields` (single) or `merged_extra_fields` (multi).

You can add new canonical fields by editing `CanonicalFields` class; they become allowed keys automatically.

---
## 9. Normalization Summary

| Aspect | Rule |
|--------|------|
| Dates | Standardized to YYYY-MM-DD when pattern matches |
| MRZ | Non‑allowed chars stripped; uppercase |
| IDs / numbers | Spaces / dashes removed, uppercased |
| Empty noise | Discarded (e.g. just dashes) |

Normalization code in `processing.normalize_value`.

---
## 10. Logging & Debug

Set `DEBUG_EXTRACTION=1` for:
- Prompt preview (truncated)
- Page sizes
- Raw model output snippet
- Salvage attempts (if empty fields)

Use `tail -f` on logs to inspect extraction issues.

---
## 11. Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Empty `fields` | Model uncertain / low contrast image | Improve scan, enable debug, check salvage log |
| Missing back page grouping | Heuristics too strict | Lower `MIN_FIELDS_FOR_NEW_DOC` or raise `MIN_KEY_OVERLAP_FOR_CONTINUATION` |
| Unexpected new group | Continuation misclassified | Inspect page key overlap; adjust heuristics |
| PDF pages cut off (single) | Over page cap | Increase `MAX_PAGES_RENDER` or use multi endpoint |
| Error `url_too_large` | Remote file size exceeded | Increase `MAX_FILE_MB` if safe |
| `model_name_may_not_be_vision_capable` warning | Text‑only model configured | Switch to a multimodal vision model |

---
## 12. Adding a New Field

1. Add the optional attribute to `CanonicalFields`
2. Restart server (no migrations needed)
3. The new key becomes available for extraction & will appear if the model provides it

---
## 13. Security Notes

- `file_path` form option (multi endpoint) should be restricted or removed in production
- Enforce auth (not included in Phase 1)
- Validate MIME types if hardening further
- Consider temporary storage directory with cleanup if adding persistence

---
## 14. Performance Notes

- Parallel page calls (async) speed up multi extraction
- 180 DPI chosen for quality/time balance
- Increase cautiously if very small font documents are common

---
## 15. Roadmap Ideas (Phase 2+)

- Optional OCR fallback for low confidence pages
- Field confidence reintegration in public response (if needed)
- Auto redaction / masking (PII control)
- Caching of repeated pages (hash based)
- Batch async ingestion queue
- Structured template hints per doc_type

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

Add your chosen license here (MIT, Apache-2.0, etc.).

---
## 18. Summary

This service offers a foundation for reliable, explainable KYC document parsing with clear extension points: prompt tuning, heuristics, normalization, and schema growth.

> Keep heuristics simple first; only complicate after measuring real errors.

