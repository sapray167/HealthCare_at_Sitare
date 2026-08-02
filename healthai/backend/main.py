import sys
import json
from pathlib import Path

# Ensure backend directory is in python path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import time
from schemas import FORM_SCHEMAS, get_schema

from extractor import extract_fields
from drafter import generate_draft
from db import (
    init_db, insert_record, update_record_draft, get_record, list_records,
    get_stats, create_user, verify_user, save_notification, update_record_merged,
    insert_pending_record, update_record_extraction, mark_notification_sent, get_conn
)
from contact_guide import detect_platform, get_field_guidance, list_platforms
from emailer import send_missing_fields_email

app = FastAPI(title="Healthcare Admin AI")

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str

class SendEmailRequest(BaseModel):
    record_id: int
    recipient_email: str

class SubmitMissingRequest(BaseModel):
    record_id: int
    filled_fields: dict

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # fine for a hackathon demo running locally
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize SQLite database on startup
init_db()


@app.post("/register")
def register(req: RegisterRequest):
    if not req.full_name or len(req.full_name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Please provide your full name.")
    if not req.email or "@" not in req.email:
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")
    if not req.password or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters long.")

    try:
        user = create_user(req.full_name, req.email, req.password)
        return {
            "status": "success",
            "message": "Account created successfully!",
            "user": user,
            "token": f"user_token_{user['id']}"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/login")
def login(req: LoginRequest):
    try:
        if not req.email or "@" not in req.email:
            raise HTTPException(status_code=400, detail="Please enter a valid email address.")
        if not req.password:
            raise HTTPException(status_code=400, detail="Please enter your password.")
        
        user = verify_user(req.email, req.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password. Please check your credentials or create a new account.")

        return {
            "status": "success",
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user.get("role", "user"),
            "token": f"user_token_{user['id']}",
            "message": "Authenticated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error during login endpoint execution: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during authentication. Please try again.")


@app.get("/form-types")
def form_types():
    """So the frontend can build the dropdown + labels dynamically."""
    return {
        key: {"label": schema["label"], "fields": schema["fields"], "required": schema["required"]}
        for key, schema in FORM_SCHEMAS.items()
    }


@app.post("/customer-upload")
async def customer_upload(file: UploadFile = File(...), form_type: str = Form(...), user_email: str = Form(...)):
    try:
        get_schema(form_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    safe_filename = f"{int(time.time())}_{file.filename.replace(' ', '_')}"
    saved_path = UPLOAD_DIR / safe_filename
    with open(saved_path, "wb") as f:
        f.write(file_bytes)

    record_id = insert_pending_record(form_type, file.filename, str(saved_path), user_email)
    return {
        "status": "success",
        "record_id": record_id,
        "filename": file.filename,
        "message": "Document uploaded successfully! Your document is pending Admin review & extraction."
    }


@app.post("/extract-record/{record_id}")
async def extract_record(record_id: int):
    rec = get_record(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found.")

    file_path_str = rec.get("file_path")
    if not file_path_str or not Path(file_path_str).exists():
        raise HTTPException(status_code=400, detail="Source document file not found for this record.")

    file_path = Path(file_path_str)
    file_bytes = file_path.read_bytes()

    try:
        result = extract_fields(file_bytes, rec.get("filename") or file_path.name, rec["form_type"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI extraction failed: {e}")

    fields = result.get("fields", {})
    total_fields = len(fields)
    missing_fields = sum(1 for info in fields.values() if isinstance(info, dict) and info.get("confidence") == "missing")

    update_record_extraction(record_id, fields, total_fields, missing_fields, status="pending_review")
    result["record_id"] = record_id
    result["status"] = "pending_review"

    return result


@app.post("/extract")
async def extract(file: UploadFile = File(...), form_type: str = Form(...), user_email: str = Form("dr.smith@health.ai")):
    try:
        get_schema(form_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    safe_filename = f"{int(time.time())}_{file.filename.replace(' ', '_')}"
    saved_path = UPLOAD_DIR / safe_filename
    with open(saved_path, "wb") as f:
        f.write(file_bytes)

    try:
        result = extract_fields(file_bytes, file.filename, form_type)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    # Store record in SQLite DB
    fields = result.get("fields", {})
    total_fields = len(fields)
    missing_fields = sum(1 for info in fields.values() if isinstance(info, dict) and info.get("confidence") == "missing")
    record_id = insert_record(form_type, file.filename, fields, total_fields, missing_fields, user_email=user_email)
    
    # Update file_path for record
    with get_conn() as conn:
        conn.execute("UPDATE records SET file_path = ? WHERE id = ?", (str(saved_path), record_id))

    result["record_id"] = record_id
    return result



@app.post("/generate", response_class=PlainTextResponse)
async def generate(form_type: str = Form(...), fields_json: str = Form(...), record_id: int = Form(None)):
    try:
        fields = json.loads(fields_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="fields_json must be valid JSON.")

    try:
        draft = generate_draft(form_type, fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if record_id:
        update_record_draft(record_id, draft)

    return draft


@app.get("/stats")
def stats(user_email: str = None):
    return get_stats(user_email=user_email)


@app.get("/records")
def records(limit: int = 50, user_email: str = None):
    return list_records(limit=limit, user_email=user_email)


@app.get("/records/{record_id}")
def record(record_id: int):
    rec = get_record(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")
    return rec


@app.get("/platforms")
def platforms():
    return list_platforms()


@app.get("/records/{record_id}/missing-details")
def missing_details(record_id: int, platform: str = None):
    rec = get_record(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")
    
    schema = FORM_SCHEMAS.get(rec["form_type"], {})
    fields_dict = json.loads(rec["fields_json"]) if rec.get("fields_json") else {}
    schema_fields = schema.get("fields", {})
    
    platform_info = detect_platform(rec.get("filename", ""), fields_dict, platform_key=platform)
    
    missing_list = []
    for k, v in fields_dict.items():
        val = v.get("value", "") if isinstance(v, dict) else str(v)
        conf = v.get("confidence", "") if isinstance(v, dict) else ""
        if conf in ["missing", "user_filled"] or not str(val).strip():
            label = schema_fields.get(k, k.replace("_", " ").title())
            guidance = get_field_guidance(k, label, platform_info)
            missing_list.append({
                "key": k,
                "label": label,
                "value": val if val else "",
                "confidence": conf,
                "contact_help": guidance
            })
            
    return {
        "id": rec["id"],
        "form_type": rec["form_type"],
        "form_label": schema.get("label", rec["form_type"]),
        "filename": rec.get("filename"),
        "missing_fields": missing_list,
        "platform_detected": platform_info["name"],
        "platform_key": platform_info.get("key", "default"),
        "all_platforms": list_platforms()
    }


@app.post("/send-missing-email")
def send_missing_email(req: SendEmailRequest):
    rec = get_record(req.record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")
    
    if not req.recipient_email or "@" not in req.recipient_email:
        raise HTTPException(status_code=400, detail="Invalid email address.")
        
    schema = FORM_SCHEMAS.get(rec["form_type"], {})
    form_label = schema.get("label", rec["form_type"])
    
    fields_dict = json.loads(rec["fields_json"]) if rec.get("fields_json") else {}
    missing_count = sum(
        1 for v in fields_dict.values() 
        if (isinstance(v, dict) and v.get("confidence") == "missing") or not str(v.get("value") if isinstance(v, dict) else v).strip()
    )
    
    form_link = f"http://localhost:8000/static/fill_missing.html?record_id={req.record_id}"
    
    res = send_missing_fields_email(
        recipient_email=req.recipient_email,
        record_id=req.record_id,
        form_label=form_label,
        filename=rec.get("filename", ""),
        missing_count=missing_count,
        form_link=form_link
    )
    
    save_notification(req.record_id, req.recipient_email, form_link)
    return res


@app.post("/submit-missing")
def submit_missing(req: SubmitMissingRequest):
    rec = get_record(req.record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")
        
    fields_dict = json.loads(rec["fields_json"]) if rec.get("fields_json") else {}
    for k, v in req.filled_fields.items():
        if k in fields_dict:
            if isinstance(fields_dict[k], dict):
                fields_dict[k]["value"] = v
                fields_dict[k]["confidence"] = "user_filled"
            else:
                fields_dict[k] = {"value": v, "confidence": "user_filled"}
        else:
            fields_dict[k] = {"value": v, "confidence": "user_filled"}

    total_fields = len(fields_dict)
    missing_count = sum(
        1 for v in fields_dict.values() 
        if (isinstance(v, dict) and v.get("confidence") == "missing") or not str(v.get("value") if isinstance(v, dict) else v).strip()
    )
    
    status = "completed" if missing_count == 0 else "pending_review"
    
    clean_fields = {k: (v.get("value", "") if isinstance(v, dict) else str(v)) for k, v in fields_dict.items()}
    try:
        draft = generate_draft(rec["form_type"], clean_fields)
    except Exception:
        draft = rec.get("draft_text", "")
        
    update_record_merged(req.record_id, fields_dict, total_fields, missing_count, status=status, draft_text=draft)
    
    return {
        "status": "success",
        "message": "Missing fields updated successfully!",
        "record_id": req.record_id,
        "remaining_missing": missing_count
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# Serve static frontend files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def read_root():
        return RedirectResponse(url="/static/login.html")
