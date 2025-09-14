import httpx
from pydantic_ai import  ImageUrl, PromptedOutput
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional

class InternationalPassport(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "passport_number": "A123456789",
                "surname": "DOE",
                "given_names": "JOHN ADAM",
                "first_name": "JOHN",
                "middle_names": "ADAM",
                "date_of_birth": "1990-01-01",
                "nationality": "NIGERIAN",
                "date_of_issue": "2020-01-01",
                "date_of_expiry": "2030-01-01",
                "sex": "M",
                "mrz_line1": "P<NGADOE<<JOHN<ADAM<<<<<<<<<<<<<<",
                "mrz_line2": "A123456789NGA9001019M3001012<<<<<<<<<<<<<<04"
            }
            
        }
    )
    
    document_code: Optional[str] = Field(None, description="Usually 'P<' on MRZ indicating passport document type")
    passport_type: Optional[str] = Field(None, description="e.g. 'STANDARD', 'OFFICIAL', 'DIPLOMATIC'")
    passport_number: str = Field(..., description="Passport number as printed")
    issuing_country: Optional[str] = Field(None, description="Country code or name, e.g. 'NIGERIA' or 'NGA'")
    nationality: Optional[str] = Field(None, description="Holder's nationality text")
    surname: Optional[str] = Field(None, description="Primary family name (SURNAME field)")
    given_names: Optional[str] = Field(None, description="All given names as a single string")
    first_name: Optional[str] = Field(None, description="First given name if separated")
    middle_names: Optional[str] = Field(None, description="Remaining given/middle names")
    date_of_birth: Optional[str] = Field(None, description="YYYY-MM-DD")
    place_of_birth: Optional[str] = Field(None, description="City / State / Country if shown")
    sex: Optional[str] = Field(None, description="M / F / X if present")
    date_of_issue: Optional[str] = Field(None, description="YYYY-MM-DD")
    date_of_expiry: Optional[str] = Field(None, description="YYYY-MM-DD")
    issuing_authority: Optional[str] = Field(None, description="e.g. 'FEDERAL REPUBLIC OF NIGERIA'")
    place_of_issue: Optional[str] = Field(None, description="Place of issue if distinct from authority")
    file_number: Optional[str] = Field(None, description="Internal file/reference number if present")
    nin: Optional[str] = Field(None, description="National Identification Number (if printed)")
    signature_present: Optional[bool] = Field(None, description="True if signature region visibly signed")
    passport_holder_signature_text: Optional[str] = Field(None, description="If the signature is rendered as text")
    mrz_line1: Optional[str] = Field(None, description="First MRZ line exactly as seen")
    mrz_line2: Optional[str] = Field(None, description="Second MRZ line exactly as seen")
    mrz_extracted_names: Optional[str] = Field(None, description="Names section parsed from MRZ if computed")
    mrz_personal_number: Optional[str] = Field(None, description="Optional personal number (from MRZ if present)")
    height: Optional[str] = Field(None, description="Height if printed (some variants might)")
    profession: Optional[str] = Field(None, description="Occupation/profession if shown")
    observations: Optional[str] = Field(None, description="Observations or endorsements text block")
    ecowas_emblem_present: Optional[bool] = Field(None, description="Detected ECOWAS emblem presence")
    coat_of_arms_present: Optional[bool] = Field(None, description="Detected national coat of arms presence")
    photo_quality_note: Optional[str] = Field(None, description="Any quality remark about the photo region")
    extra_security_features: Optional[str] = Field(None, description="Visible holograms, optically variable inks, etc.")
    scan_quality: Optional[str] = Field(None, description="Assessment: excellent/good/fair/poor")
    extraction_notes: Optional[str] = Field(None, description="General notes about OCR/extraction issues")
    
    
    
model_name = "gemma3:4b"
        
ollama_model = OpenAIChatModel(
    model_name=model_name,
    provider=OpenAIProvider(base_url='http://localhost:11434/v1'),
)

system_prompt="""You extract ONLY visible fields from a Nigerian ECOWAS passport biodata page.
Output ONLY valid JSON for InternationalPassport. Omit absent fields. No prose, no markdown, no explanations."""

agent = Agent(ollama_model, instructions=system_prompt, 
              output_type=PromptedOutput(
                [InternationalPassport], 
                name='InternationalPassport',
                description='Extract all visible fields from the Nigerian ECOWAS passport biodata page.'
    ))


# image_response = httpx.get('ttps://iili.io/3Hs4FMg.png')
Imageurl = "https://res.cloudinary.com/dihrudimf/image/upload/v1756159121/Nationl_iD_test_komonm.jpg"
resp = httpx.get(Imageurl, timeout=30)
resp.raise_for_status()

result = agent.run_sync(
    [
        "Extract fields from this passport image",
        # ImageUrl(url='https://iili.io/3Hs4FMg.png'),
        BinaryContent(data=resp.content, media_type='image/jpg')
    ]
)
print(result.output)

