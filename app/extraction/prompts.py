"""Central prompt templates for vision extraction.

Why a separate module?
    Keeping prompt strategy isolated prevents business logic files from
    accumulating large multi-line strings and allows iteration / A-B testing
    of instructions without touching core pipeline code.

High-level contents:
    SYSTEM_PROMPT_BASE : Baseline instruction set (anti-hallucination + schema rules).
    build_prompt()     : Helper that injects allowed canonical keys, optional doc_type hint,
                         and toggles confidence strictness.

All consumer code should call build_prompt instead of concatenating strings
manually so that future global adjustments propagate everywhere consistently.
"""
from typing import List

SYSTEM_PROMPT_BASE = """You are an expert document analyzer specialized in accurate extraction of structured data from any type of document.

CORE MISSION:
Extract ONLY information EXPLICITLY VISIBLE in the document. Accuracy is your absolute top priority.

EXTRACTION PHILOSOPHY:
1. VERIFIED CAPTURE: Extract ONLY structured information you can directly see and verify
2. INTELLIGENT FIELD MAPPING: Use standard schema fields when applicable, extra_fields for everything else
3. DYNAMIC ADAPTATION: Adapt extraction strategy based on document type and content
4. ACCURACY FIRST: Only extract information that is explicitly visible - NEVER hallucinate fields
5. MEANINGFUL LABELING: Create descriptive field names that clearly indicate content

STRICT GUIDELINES:
1. Extract ONLY fields that are EXPLICITLY present in the document or image
2. Use standard schema fields for common information (names, dates, document numbers, etc.)
3. Use 'extra_fields' for document-specific information that doesn't fit standard fields
4. For each extracted field, prefer returning an object with 'value' and 'confidence' (0-1). If the system only consumes plain values you may still internally assess confidence.
5. Create meaningful field names in extra_fields that describe the content
6. Do not include explanations - return ONLY JSON
7. If unsure about a field, omit it (do NOT guess).

ANTI-HALLUCINATION REQUIREMENTS:
1. ONLY extract information you literally see
2. NEVER infer or guess hidden data
3. Omission preferred over hallucination
4. Use lower confidence (<0.6) for partially unclear text

OUTPUT CONTRACT:
Return JSON with keys: doc_type, fields, extra_fields.
fields: only allowed canonical keys present on the document.
extra_fields: other clearly labeled values (use descriptive snake_case names).
Each field value MUST be an object: {"value": <string>, "confidence": <float 0-1>}.
If no values: use empty objects: "fields": {}, "extra_fields": {}.
No markdown, no prose.

CONTINUATION RULE:
If this page is clearly a continuation (e.g. signatures, attestations, durations, restrictions, back side, terms) of a prior document in the SAME uploaded file, REUSE the exact same previously emitted doc_type string instead of inventing or guessing a new one. Only emit a new doc_type when the visual layout and content indicate a truly different document.
""".strip()


# Quick reference (duplicated intentionally for nearby visibility):
#   Return JSON with keys: doc_type, fields, extra_fields.
#   fields: only allowed canonical keys present on the document.
#   extra_fields: other clearly labeled values (use descriptive snake_case names).
#   No markdown, no prose.



# Legacy version (commented out, kept for historical context):
# def build_prompt(doc_type: str | None, allowed_keys: List[str]) -> str:
#     """Return a single consolidated system prompt (no separate user prompt).
#
#     Earlier iterations used a simpler function signature without confidence
#     control; we preserve it here so diffs show evolution of the interface.
#     The routes layer and vision_model_client will treat this as the sole instruction
#     string; any prior user prompt content has been folded into the system prompt.
#     """
def build_prompt(doc_type: str | None, allowed_keys: List[str], require_conf: bool = True) -> str:
    """Return a full system prompt string tailored to one extraction call.

    Parameters:
        doc_type     : Optional hint (front-side pages where type is known). If None, model infers.
        allowed_keys : Canonical field whitelist inserted inline for model grounding.
        require_conf : If True, model is instructed that every field object MUST include
                       {"value", "confidence"}. If False, confidence becomes best-effort
                       (useful for weaker models that otherwise hallucinate numbers).

    Design choices:
        - We inline allowed_keys directly (not separate message) to reduce token / turn complexity.
        - Confidence strictness is feature-flagged so product tiers / model swaps are easy.
        - The base instructions (SYSTEM_PROMPT_BASE) emphasize anti‑hallucination; we append
          only the dynamic elements here.
    """
    allowed_list = ", ".join(allowed_keys)
    type_hint = f"Document type hint: {doc_type}." if doc_type else "Infer the document type from visual cues."
    conf_clause = (
        "Each field value MUST be an object: {\"value\": <string>, \"confidence\": <float 0-1>}."
        if require_conf else
        "Prefer objects {\"value\": <string>, \"confidence\": <float 0-1>}; if you cannot provide confidence, return just the string (do NOT invent)."
    )
    return (
        f"{SYSTEM_PROMPT_BASE}\nAllowed canonical keys: [{allowed_list}]. {type_hint}\n"
        f"{conf_clause}\nReturn ONLY JSON with keys: doc_type, fields, extra_fields. "
        "If none present use empty objects. No commentary."
    )
    
    
    # Historical alternative (retained for reference—shows earlier messaging
    # emphasizing minimal JSON even when empty). Keeping this helps future
    # maintainers understand why strict empty object rules exist.
    # allowed_list = ", ".join(allowed_keys)  # canonical keys enumerated inline
    # type_hint = f"Document type hint: {doc_type}." if doc_type else "Infer the document type from visual cues."
    # system_prompt = (
    #     f"{SYSTEM_PROMPT_BASE}\nAllowed canonical keys: [{allowed_list}].\n, [{type_hint}].\n"
    # "Return ONLY JSON with keys: doc_type, fields, extra_fields. If a key has no visible values, use an empty object (e.g. 'fields': {}). Do NOT omit 'fields' or 'extra_fields'.\n"
    # "Example minimal JSON (no values yet): {\"doc_type\": \"passport\", \"fields\": {}, \"extra_fields\": {}}"
    # )
    # return system_prompt
