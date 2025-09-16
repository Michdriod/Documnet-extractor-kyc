"""Pydantic models for API outputs and intermediate raw fields.

Layers / roles:
    CanonicalFields        : Optional superset of identity + document keys used for grounding prompts.
    FieldWithConfidence    : Normalized wrapper for a single extracted value + confidence score.
    FlatExtractionResult   : Public API shape (doc_type + two maps of field objects). Can accept legacy plain strings.
    ErrorEnvelope          : Consistent error response body for FastAPI handlers.

Historical notes:
    Earlier versions exposed separate parallel confidence maps (fields_confidence, extra_fields_confidence).
    We keep commented examples so future diffs show evolution and to permit quick rollback if needed.
"""

from typing import Dict, Optional, List, Any, Union
from pydantic import BaseModel, Field


class CanonicalFields(BaseModel):
    """Flexible identity field superset (all optional to reduce hallucination).

    This is intentionally broad; prompts enumerate allowed keys so the model
    anchors extractions to real-world document semantics (names, dates, IDs...).
    All fields are optional to discourage the model from fabricating values just
    to satisfy required schema positions.
    """

    # Core person identifiers
    surname: Optional[str] = None
    given_names: Optional[str] = None
    first_name: Optional[str] = None
    middle_names: Optional[str] = None
    full_name: Optional[str] = None
    alias_name: Optional[str] = None

    # Document numbers / identifiers
    document_number: Optional[str] = None
    passport_number: Optional[str] = None
    national_id_number: Optional[str] = None
    nin: Optional[str] = None
    voter_id_number: Optional[str] = None
    driver_license_number: Optional[str] = None
    license_number: Optional[str] = None
    permit_number: Optional[str] = None
    work_permit_number: Optional[str] = None
    residence_permit_number: Optional[str] = None
    tax_id_number: Optional[str] = None
    social_security_number: Optional[str] = None
    account_number: Optional[str] = None
    customer_number: Optional[str] = None
    reference_number: Optional[str] = None
    file_number: Optional[str] = None
    card_number: Optional[str] = None
    folio_number: Optional[str] = None
    deed_number: Optional[str] = None
    parcel_number: Optional[str] = None
    plot_number: Optional[str] = None
    survey_plan_number: Optional[str] = None
    title_number: Optional[str] = None
    certificate_number: Optional[str] = None

    # MRZ
    mrz_line1: Optional[str] = None
    mrz_line2: Optional[str] = None
    mrz_line3: Optional[str] = None

    # Dates
    date_of_birth: Optional[str] = None
    place_of_birth: Optional[str] = None
    date_of_issue: Optional[str] = None
    date_of_expiry: Optional[str] = None
    date_of_registration: Optional[str] = None
    date_of_execution: Optional[str] = None
    date_of_signature: Optional[str] = None
    date_of_transfer: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    effective_date: Optional[str] = None
    statement_period_start: Optional[str] = None
    statement_period_end: Optional[str] = None
    billing_period_start: Optional[str] = None
    billing_period_end: Optional[str] = None

    # Classification / type
    document_type_label: Optional[str] = None
    document_category: Optional[str] = None
    class_code: Optional[str] = None
    vehicle_class: Optional[str] = None
    license_class: Optional[str] = None
    restriction_codes: Optional[str] = None
    endorsement_codes: Optional[str] = None

    # Nationality / country
    nationality: Optional[str] = None
    nationality_code: Optional[str] = None
    issuing_country: Optional[str] = None
    issuing_authority: Optional[str] = None
    country_of_issue: Optional[str] = None

    # Personal attributes
    sex: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    profession: Optional[str] = None
    occupation: Optional[str] = None
    tribe: Optional[str] = None
    religion: Optional[str] = None
    height: Optional[str] = None
    weight: Optional[str] = None
    eye_color: Optional[str] = None
    hair_color: Optional[str] = None
    distinguishing_marks: Optional[str] = None
    signature_present: Optional[bool] = None

    # Contact & address
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    address_line3: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    province: Optional[str] = None
    region: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    residence_status: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None

    # Voter / election specifics
    polling_unit: Optional[str] = None
    ward: Optional[str] = None
    lga: Optional[str] = None
    constituency: Optional[str] = None
    state_code: Optional[str] = None
    vin: Optional[str] = None  # voter identification number alias

    # Driver license specifics
    issuing_office: Optional[str] = None
    driver_restrictions: Optional[str] = None
    driver_endorsements: Optional[str] = None
    driver_conditions: Optional[str] = None
    vehicle_categories: Optional[str] = None

    # Financial / statement
    bank_name: Optional[str] = None
    branch_name: Optional[str] = None
    iban: Optional[str] = None
    swift_code: Optional[str] = None
    balance: Optional[str] = None
    currency: Optional[str] = None

    # Utility bill
    meter_number: Optional[str] = None
    account_name: Optional[str] = None
    service_address: Optional[str] = None
    tariff: Optional[str] = None
    billing_reference: Optional[str] = None

    # Property / land / agreement
    property_address: Optional[str] = None
    property_description: Optional[str] = None
    land_size: Optional[str] = None
    coordinates: Optional[str] = None
    grantor_name: Optional[str] = None
    grantee_name: Optional[str] = None
    consideration_amount: Optional[str] = None
    tenure_type: Optional[str] = None
    encumbrances: Optional[str] = None

    # Permit / visa
    visa_number: Optional[str] = None
    visa_type: Optional[str] = None
    visa_category: Optional[str] = None
    visa_entries: Optional[str] = None
    visa_issue_place: Optional[str] = None

    # Misc / meta
    barcode_value: Optional[str] = None
    qr_code_value: Optional[str] = None
    hash_value: Optional[str] = None
    notes: Optional[str] = None
    observations: Optional[str] = None
    warnings: Optional[str] = None
    seal_present: Optional[bool] = None
    hologram_present: Optional[bool] = None
    watermark_present: Optional[bool] = None




class FieldWithConfidence(BaseModel):
    """Container for a single extracted value and its confidence score.

    confidence is expected to be 0..1. Upstream model may omit or produce
    out-of-range numbers; from_any() clamps or substitutes defaults.
    """

    value: str
    confidence: float

    @classmethod
    def from_any(cls, raw, default_conf: float, lo: float = 0.0, hi: float = 1.0):
        if isinstance(raw, cls):
            return cls(
                value=raw.value,
                confidence=_clamp(raw.confidence, lo, hi, default_conf)
            )
        if isinstance(raw, dict):
            val = str(raw.get("value", "")).strip()
            conf = raw.get("confidence", default_conf)
        else:
            val = str(raw).strip()
            conf = default_conf
        try:
            conf_f = float(conf)
        except Exception:
            conf_f = default_conf
        result = cls(value=val, confidence=_clamp(conf_f, lo, hi, default_conf))
        print(f"Created FieldWithConfidence: {result}")  # Debugging
        return result

def _clamp(v: float, lo: float, hi: float, fallback: float) -> float:
    if not (lo <= v <= hi):
        return fallback
    return v

class FlatExtractionResult(BaseModel):
    """Normalized extraction payload returned to API clients.

    doc_type      : Free-form string describing detected document class (may be None if uncertain).
    fields        : Canonical keys present on the document -> FieldWithConfidence (or legacy plain string).
    extra_fields  : Non-canonical but useful labeled values -> FieldWithConfidence (or legacy plain string).

    Backward compatibility: accepts plain string values so historical callers
    that haven't normalized yet won't break; internal code should migrate to
    FieldWithConfidence for richer downstream analytics.
    """

    doc_type: Optional[str] = None
    fields: Dict[str, Union[str, FieldWithConfidence]] = Field(default_factory=dict)
    extra_fields: Dict[str, Union[str, FieldWithConfidence]] = Field(default_factory=dict)
    # Legacy confidence maps retained (commented) for possible reintroduction:
    # fields_confidence: Dict[str, float] = Field(default_factory=dict)
    # extra_fields_confidence: Dict[str, float] = Field(default_factory=dict)

# class FlatExtractionResult(BaseModel):  # simplified output for single document
#     """Return shape including confidence maps (now always provided).

#     fields / extra_fields map field_name -> string value.
#     fields_confidence / extra_fields_confidence map field_name -> float confidence 0..1.
#     """
#     doc_type: Optional[str] = None
#     fields: Dict[str, str]
#     extra_fields: Dict[str, str] = Field(default_factory=dict)
#     fields_confidence: Dict[str, float] = Field(default_factory=dict)
#     extra_fields_confidence: Dict[str, float] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):  # consistent error body (unused for success)
    """Uniform error body returned on failure.

    error: {"code": string, "message": string} (code optional depending on caller).
    """

    error: Dict[str, str]
