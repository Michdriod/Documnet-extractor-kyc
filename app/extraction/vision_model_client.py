"""Model client abstraction layer.

Extended description:
        * Encapsulates provider/model setup (currently Groq) so swapping vendors
            only touches this file.
        * Exposes a single async API (VisionExtractor.run) returning a dict that
            contains the parsed RawExtraction object + timing + raw assistant text.
        * Adds salvage heuristics for empty structured outputs to improve resilience.
        * Maintains backwards-compatible commented sections for historical context.
"""

from typing import List, Dict, Any, Optional
import time
import json
import logging
from pydantic_ai import Agent, BinaryContent, PromptedOutput
from pydantic import BaseModel, Field
from app.core.config import get_settings
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from app.extraction.prompts import SYSTEM_PROMPT_BASE
from pydantic_ai import Agent
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider



system_prompt=SYSTEM_PROMPT_BASE  # Base system instructions reused (legacy variable; may be overridden later)

class RawExtraction(BaseModel):
    """Loose model for initial LLM JSON prior to normalization.

    Rationale:
        The first pass from the model may vary (scalars vs objects). We keep
        field value types permissive (Any) and rely on a downstream normalizer
        to coerce into FieldWithConfidence objects required by API outputs.
    """

    doc_type: str | None = None
    fields: Dict[str, Any] = Field(default_factory=dict)
    extra_fields: Dict[str, Any] = Field(default_factory=dict)
    # fields_confidence: Dict[str, float] = Field(default_factory=dict)
    # extra_fields_confidence: Dict[str, float] = Field(default_factory=dict)


class VisionExtractor:
    """High-level orchestrator for single-call vision extraction.

    Key points:
        - Centralizes model construction + logging.
        - Accepts either a raw system prompt string or (prompt, description) tuple.
        - Leverages pydantic-ai's PromptedOutput to parse JSON directly into
          the RawExtraction pydantic model (strongly-typed output).
        - Minimizes chat turns by embedding all guidance in the system prompt.
    """

    DEFAULT_DESCRIPTION = (
        "Return JSON with keys: doc_type (string), fields (object of visible canonical field values), "
        "extra_fields (object for any other visible labeled values)."
    )

    description = DEFAULT_DESCRIPTION  # Default structural description (can be overridden)

    # USER_PROMPT_BASE (historical, retained for context):
    # """ACCURATE DOCUMENT EXTRACTION FROM IMAGE:
    #
    # Analyze the provided document images and extract ONLY information that is explicitly visible.
    # Follow anti-hallucination protocol strictly. If a value cannot be verified, omit it.
    # Return ONLY valid JSON (no text before or after).""".strip()
    # This guidance is now integrated into SYSTEM_PROMPT_BASE.

    def __init__(self):
        # OpenAI/Ollama alternative path (commented; enables quick provider swap):
        # self.settings = get_settings()
        # self.model = OpenAIChatModel(
        #     model_name=self.settings.VISION_MODEL,
        #     provider=OpenAIProvider(base_url=f"{self.settings.OLLAMA_BASE_URL}/v1"),
        # )
        # Keeping this commented block documents how to pivot to a local gateway.

        self.settings = get_settings()
        groq_key = self.settings.GROQ_API_KEY
        if not groq_key:
            raise RuntimeError("GROQ_API_KEY is required and no fallback is allowed.")
        try:
            self.model = GroqModel(
                model_name=self.settings.VISION_MODEL,
                provider=GroqProvider(api_key=groq_key),
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Groq provider: {e}") from e

    def build_agent(self, system_prompt: str, description: str | None = None) -> Agent:
        """Instantiate an agent with the system prompt and optional description.

        Description (if provided) is stored in the output metadata and can help
        the model reason about desired JSON structure without adding another
        chat message turn.
        """
        if self.settings.DEBUG_EXTRACTION:
            logging.getLogger("kyc.extract").debug(
                "agent_build system_prompt_preview=%s desc_preview=%s",
                system_prompt[:220].replace('\n', ' '),
                (description or self.DEFAULT_DESCRIPTION)[:160].replace('\n', ' '),
            )

        return Agent(
            self.model,
            instructions=system_prompt,
            output_type=PromptedOutput(
                [RawExtraction],
                name="RawExtraction",
                description=description
            ),
        )

    async def run(self, prompt: str | tuple, images: List[bytes]) -> Dict[str, Any]:
        """Execute the model call.

        Accepts either a single system prompt string, or a (system_prompt, description)
        tuple where the description is injected via PromptedOutput instead of as a
        separate user message.
        """
        log = logging.getLogger("kyc.extract")
        system_prompt: str
        description: str | None = None
        if isinstance(prompt, tuple):
            system_prompt, description = prompt  # second element repurposed
        else:
            system_prompt = prompt
        if self.settings.DEBUG_EXTRACTION:
            img_sizes = [len(b) for b in images]
            log.debug(
                "model_run start model=%s images=%d img_sizes=%s has_description=%s",
                self.settings.VISION_MODEL,
                len(images),
                img_sizes,
                bool(description),
            )
            # Heuristic: warn early if model name unlikely vision-capable
            if all(tok not in self.settings.VISION_MODEL.lower() for tok in ["llava", "vision", "clip", "mm", "multi", "pix", "phi-3-vision", "llama", "gemma3:4b", "minicpm-v:latest", "minicpm-v"]):
                log.warning("model_name_may_not_be_vision_capable model=%s", self.settings.VISION_MODEL)
        agent = self.build_agent(system_prompt, description)
        inputs: List[Any] = []  # Ordered binary contents to agent
        # Only images now; all textual guidance lives in the system prompt.
        for img in images:
            inputs.append(BinaryContent(data=img, media_type="image/png"))
        t0 = time.time()
        try:
            result = await agent.run(inputs)
            print(result.output)  # stdout debug (retained intentionally; can convert to logger)
        except Exception as e:
            log.error("model_run_exception error=%s", e, exc_info=True)
            raise
        latency_ms = int((time.time() - t0) * 1000)
        raw_obj = result.output
        raw_text = None
        model_message_text = None
        # Attempt to recover raw assistant text for debugging (version-dependent attributes).
        try:
            if hasattr(result, 'raw_response'):
                raw_text = getattr(result, 'raw_response', None)
            # Attempt to extract first assistant message text
            for attr in ("messages", "all_messages", "message_history"):
                msg_seq = getattr(result, attr, None)
                if msg_seq:
                    # Look for last/first assistant content
                    for m in reversed(msg_seq):
                        if isinstance(m, dict):
                            role = m.get("role") or m.get("type")
                            content = m.get("content")
                        else:
                            role = getattr(m, "role", None)
                            content = getattr(m, "content", None)
                        if role in {"assistant", "model"} and content:
                            if isinstance(content, list):
                                # OpenAI style content parts
                                text_parts = [c.get("text") for c in content if isinstance(c, dict) and c.get("type") == "text" and c.get("text")]
                                if text_parts:
                                    model_message_text = "\n".join(text_parts)
                            elif isinstance(content, str):
                                model_message_text = content
                            break
                    if model_message_text:
                        break
        except Exception:
            pass
        if self.settings.DEBUG_EXTRACTION:
            try:
                log.debug(
                    "model_run raw_output_preview=%s latency_ms=%d",
                    json.dumps(raw_obj.dict() if hasattr(raw_obj, 'dict') else raw_obj)[:400],
                    latency_ms,
                )
            except Exception:
                log.debug(
                    "model_run raw_output_type=%s latency_ms=%d",
                    type(raw_obj),
                    latency_ms,
                )
            if model_message_text:
                log.debug("model_run assistant_text_snippet=%s", model_message_text[:400].replace('\n', ' '))
            elif raw_text:
                log.debug("model_run raw_text_fallback_snippet=%s", str(raw_text)[:400].replace('\n', ' '))
        empty_fields = hasattr(raw_obj, 'fields') and not getattr(raw_obj, 'fields')
        if empty_fields and self.settings.DEBUG_EXTRACTION:
            log.warning(
                "model_run_empty_fields model=%s latency_ms=%d", self.settings.VISION_MODEL, latency_ms
            )
            # Attempt naive salvage from raw_text if present (best effort; avoids silent empty responses)
            salvage = {}
            if raw_text and isinstance(raw_text, str):
                import re
                # Look for simple key:value patterns (alphanumeric keys, colon, short value)
                for m in re.finditer(r"(passport_number|surname|given_names|first_name|middle_names|date_of_birth|date_of_issue|date_of_expiry|nationality|issuing_country)\s*[:=]\s*([A-Za-z0-9<\-/ ]{3,64})", raw_text, re.IGNORECASE):
                    k = m.group(1).lower()
                    v = m.group(2).strip()
                    salvage[k] = v
                if salvage:
                    try:
                        # Inject salvaged fields so downstream pipeline has something
                        current = getattr(raw_obj, 'fields', {})
                        current.update({k: v for k, v in salvage.items() if k not in current})
                        setattr(raw_obj, 'fields', current)
                        log.debug("salvage_applied fields=%d", len(salvage))
                    except Exception:
                        log.debug("salvage_failed")
        return {
            "raw": raw_obj,
            "latency_ms": latency_ms,
            "used_description": description,
            "raw_text": raw_text or model_message_text,
            "assistant_text": model_message_text,
        }


# Singleton instance reused per process (stateless usage in Phase 1)
vision_extractor = VisionExtractor()
