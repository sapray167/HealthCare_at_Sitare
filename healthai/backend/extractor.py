import base64
import json
import os
from pathlib import Path
from dotenv import load_dotenv

import google.generativeai as genai

from schemas import get_schema

# Load environment variables from .env file if present
load_dotenv()

def _configure_genai():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    load_dotenv(override=True)
    
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Gemini API key is missing. Please create a .env file in the backend folder with GEMINI_API_KEY=your_key or set the GEMINI_API_KEY environment variable.")
    genai.configure(api_key=api_key)


MODEL = "gemini-3.5-flash"

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _media_type(filename: str) -> str:
    ext = os.path.splitext(filename.lower())[1]
    if ext not in MEDIA_TYPES:
        raise ValueError(f"Unsupported file type '{ext}'. Use PDF, PNG, JPG, or WEBP.")
    return MEDIA_TYPES[ext]


def _build_prompt(form_type: str) -> str:
    schema = get_schema(form_type)
    field_lines = "\n".join(f'- "{k}": {v}' for k, v in schema["fields"].items())
    required = ", ".join(schema["required"])

    return f"""You are extracting structured data from a scanned/uploaded {schema['label']} form for a healthcare administrative tool.

Extract the following fields from the document:
{field_lines}

Required fields (flag clearly if missing): {required}

Return ONLY a JSON object, no other text, no markdown fences, in exactly this shape:
{{
  "fields": {{
    "<field_key>": {{
      "value": "<extracted value, or empty string if not found>",
      "confidence": "high" | "medium" | "low" | "missing"
    }},
    ...
  }},
  "missing_required": ["<field_key>", ...],
  "notes": "<any brief note about illegible text, ambiguity, or anything a human reviewer should double check>"
}}

Rules:
- Use "missing" confidence + empty value for any field you cannot find in the document at all.
- Use "low" confidence for fields you extracted but are genuinely unsure about (unclear handwriting, ambiguous formatting).
- Never guess or fabricate a value — if it's not in the document, mark it missing.
- "missing_required" must list every required field above that ended up with confidence "missing".
- Output raw JSON only."""


def extract_fields(file_bytes: bytes, filename: str, form_type: str) -> dict:
    _configure_genai()
    media_type = _media_type(filename)

    prompt = _build_prompt(form_type)

    try:
        model = genai.GenerativeModel(MODEL)
        response = model.generate_content(
            [
                {"mime_type": media_type, "data": file_bytes},  # raw bytes — SDK handles encoding
                prompt,
            ],
            generation_config={"response_mime_type": "application/json"},
        )
    except Exception as e:
        if "401" in str(e) or "authentication" in str(e).lower() or "ACCESS_TOKEN_TYPE_UNSUPPORTED" in str(e):
            raise ValueError("Invalid Gemini API Key in backend/.env. Please get a free API key from https://aistudio.google.com/apikey and set GEMINI_API_KEY in backend/.env")
        raise e

    text = response.text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {e}\nRaw output: {text[:500]}")

    return parsed
