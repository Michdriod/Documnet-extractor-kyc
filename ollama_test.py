import base64
import json
import requests
from pathlib import Path
from typing import Optional, Dict, Any

STRUCTURED_PROMPT = """You produce EXACT JSON ONLY. No markdown, no explanation, no backticks.

Output a SINGLE JSON object with EXACT keys:
{
  "doc_type": "<string or null>",
  "fields": { },
  "extra_fields": { }
}

Rules:
1. "doc_type": infer a concise type (passport, national_id, id_card) or null.
2. "fields": ONLY common identification fields using these exact key names if (and only if) they are (supposedly) present:
   accepted keys: surname, given_names, first_name, middle_names, name, middle_name, date_of_birth, dob,
   nationality, nationality_code, sex, gender, passport_number, id_number, document_number,
   issuing_country, issuing_authority, date_of_issue, date_of_expiry, expiry_date, mrz, mrz_line1, mrz_line2
3. "extra_fields": any other clearly labeled data not fitting the above keys.
4. Do NOT invent data. If unsure, omit that key entirely.
5. Keep dates as seen (do not reformat unless trivial like DD/MM/YYYY -> YYYY-MM-DD is obvious).
6. If a section is empty leave it as {} (not null, not omitted).
7. ABSOLUTELY FORBIDDEN: markdown fences, comments, trailing commas, explanations.

Return ONLY the JSON object. NOTHING else.

VALID MINIMAL EXAMPLES:
{"doc_type": "passport", "fields": {}, "extra_fields": {}}
{"doc_type": null, "fields": {"surname":"DOE"}, "extra_fields": {}}

Now produce the JSON:
"""

def _read_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")

def _download_to_temp(url: str, temp_name: str = "._ollama_struct_img") -> Path:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    p = Path(temp_name)
    p.write_bytes(resp.content)
    return p

def _extract_json(text: str) -> Dict[str, Any]:
    """
    Try to parse strict JSON. If the model added noise, attempt a bracket slice salvage.
    Returns a dict (possibly empty on total failure).
    """
    text = text.strip()
    # Direct attempt
    try:
        return json.loads(text)
    except Exception:
        pass
    # Salvage by finding outermost braces
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            return {}
    return {}

def extract_structured(
    image_path: Optional[str] = None,
    image_url: Optional[str] = None,
    model: str = "gemma3:4b",
    prompt: str = STRUCTURED_PROMPT,
    timeout: int = 180,
    stream: bool = False,
    keep_temp: bool = False,
) -> Dict[str, Any]:
    """
    Call Ollama directly to get structured JSON.
    Provide exactly one of image_path or image_url.
    """
    if (not image_path and not image_url) or (image_path and image_url):
        raise ValueError("Provide exactly one of image_path or image_url.")

    temp_file: Optional[Path] = None
    try:
        if image_url:
            temp_file = _download_to_temp(image_url)
            image_path = str(temp_file)

        img_path = Path(image_path).expanduser().resolve()
        if not img_path.exists():
            return {
                "model": model,
                "source": {"path": str(img_path), "url": image_url},
                "raw_text": "",
                "parsed": {},
                "error": f"image_not_found:{img_path}"
            }

        try:
            img_b64 = _read_to_base64(img_path)
        except Exception as e:
            return {
                "model": model,
                "source": {"path": str(img_path), "url": image_url},
                "raw_text": "",
                "parsed": {},
                "error": f"encode_failed:{e}"
            }

        payload = {
            "model": model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": stream
        }

        try:
            resp = requests.post(
                "http://localhost:11434/api/generate",
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as e:
            return {
                "model": model,
                "source": {"path": str(img_path), "url": image_url},
                "raw_text": "",
                "parsed": {},
                "error": f"http_error:{e}"
            }

        if resp.status_code != 200:
            return {
                "model": model,
                "source": {"path": str(img_path), "url": image_url},
                "raw_text": resp.text[:400],
                "parsed": {},
                "error": f"bad_status:{resp.status_code}"
            }

        if stream:
            # Not handling NDJSON assembly here for simplicity
            raw_text = resp.text
        else:
            try:
                data = resp.json()
                raw_text = (data.get("response") or "").strip()
            except Exception:
                raw_text = resp.text.strip()

        parsed = _extract_json(raw_text)

        # Ensure minimal structure if model gave nothing
        if not parsed:
            parsed = {
                "doc_type": None,
                "fields": {},
                "extra_fields": {}
            }

        # Safety defaults
        parsed.setdefault("doc_type", None)
        parsed.setdefault("fields", {})
        parsed.setdefault("extra_fields", {})

        return {
            "model": model,
            "source": {"path": str(img_path), "url": image_url},
            "raw_text": raw_text,
            "parsed": parsed,
            "error": None if parsed.get("fields") or parsed.get("extra_fields") else "empty_structured"
        }
    finally:
        if temp_file and temp_file.exists() and not keep_temp:
            try:
                temp_file.unlink()
            except OSError:
                pass

if __name__ == "__main__":
    # Local test
    print(extract_structured(image_path="/Users/mac/Downloads/Nationl_iD test.jpeg"))
    # Remote test
    # print(extract_structured(image_url="https://res.cloudinary.com/dihrudimf/image/upload/v1756159121/Nationl_iD_test_komonm.jpg"))