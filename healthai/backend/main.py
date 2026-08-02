import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from schemas import FORM_SCHEMAS, get_schema
from extractor import extract_fields
from drafter import generate_draft
from db import (
    get_supabase,
    init_db, insert_record, update_record_draft, get_record, list_records,
    get_stats, create_user, verify_user, save_notification, update_record_merged,
    insert_pending_record, update_record_extraction, mark_notification_sent
)
from contact_guide import detect_platform, get_field_guidance, list_platforms
from emailer import send_missing_fields_email
from storage import upload_file_to_storage, download_file_from_storage

app = FastAPI(title="Healthcare Admin AI")

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str
    role: str = "user"
    org_id: str = None

class SendEmailRequest(BaseModel):
    record_id: int
    recipient_email: str

class SubmitMissingRequest(BaseModel):
    record_id: int
    filled_fields: dict

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    if request.method == "OPTIONS":
        response = Response(status_code=200)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    try:
        response = await call_next(request)
    except Exception as exc:
        response = JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error: {str(exc)}"}
        )

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

# Initialize database
init_db()


def parse_fields_json(raw_val) -> dict:
    if not raw_val:
        return {}
    if isinstance(raw_val, dict):
        return raw_val
    if isinstance(raw_val, str):
        try:
            parsed = json.loads(raw_val)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


@app.post("/register")
@app.post("/api/register")
def register(req: RegisterRequest):
    if not req.full_name or len(req.full_name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Please provide your full name.")
    if not req.email or "@" not in req.email:
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")
    if not req.password or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters long.")

    role = (req.role or "user").strip().lower()
    if role == "admin":
        if not req.org_id or req.org_id.strip().lower() != "sap167":
            raise HTTPException(
                status_code=400,
                detail="Invalid Organisation ID. Only authorized administrators with Organisation ID (sap167) can register as Admin."
            )

    try:
        user = create_user(req.full_name, req.email, req.password, role=role)
        return {
            "status": "success",
            "message": f"{'System Admin' if role == 'admin' else 'Customer'} account created successfully!",
            "user": user,
            "token": f"user_token_{user['id']}"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/login")
@app.post("/api/login")
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
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")


@app.get("/form-types")
@app.get("/api/form-types")
def form_types():
    return {
        key: {"label": schema["label"], "fields": schema["fields"], "required": schema["required"]}
        for key, schema in FORM_SCHEMAS.items()
    }


@app.post("/customer-upload")
@app.post("/api/customer-upload")
async def customer_upload(file: UploadFile = File(...), form_type: str = Form(...), user_email: str = Form(...)):
    try:
        get_schema(form_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    file_bytes = await file.read()

    try:
        storage_path = upload_file_to_storage(
            file_bytes=file_bytes,
            filename=file.filename,
            user_email=user_email
        )
    except Exception:
        storage_path = f"uploads/{int(time.time())}_{file.filename}"

    record_id = insert_pending_record(
        form_type,
        file.filename,
        storage_path,
        user_email
    )
    return {"status": "success", "record_id": record_id}


@app.post("/extract-record/{record_id}")
@app.post("/api/extract-record/{record_id}")
async def extract_record(record_id: int):
    rec = get_record(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found.")

    storage_path = rec.get("file_path")
    if not storage_path:
        raise HTTPException(status_code=400, detail="Document path missing.")

    file_bytes = download_file_from_storage(storage_path)

    try:
        result = extract_fields(file_bytes, rec.get("filename", "document.pdf"), rec["form_type"])
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
@app.post("/api/extract")
async def extract(file: UploadFile = File(...), form_type: str = Form(...), user_email: str = Form("dr.smith@health.ai")):
    try:
        get_schema(form_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    try:
        storage_path = upload_file_to_storage(
            file_bytes=file_bytes,
            filename=file.filename,
            user_email=user_email
        )
    except Exception:
        storage_path = f"uploads/{int(time.time())}_{file.filename}"

    try:
        result = extract_fields(file_bytes, file.filename, form_type)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    fields = result.get("fields", {})
    total_fields = len(fields)
    missing_fields = sum(1 for info in fields.values() if isinstance(info, dict) and info.get("confidence") == "missing")
    record_id = insert_record(form_type, file.filename, fields, total_fields, missing_fields, user_email=user_email)

    result["record_id"] = record_id
    return result


@app.post("/generate", response_class=PlainTextResponse)
@app.post("/api/generate", response_class=PlainTextResponse)
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
@app.get("/api/stats")
def stats(user_email: str = None):
    return get_stats(user_email=user_email)


@app.get("/records")
@app.get("/api/records")
def records(limit: int = 50, user_email: str = None):
    return list_records(limit=limit, user_email=user_email)


@app.get("/records/{record_id}")
@app.get("/api/records/{record_id}")
def record(record_id: int):
    rec = get_record(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")
    return rec


@app.get("/platforms")
@app.get("/api/platforms")
def platforms():
    return list_platforms()


@app.get("/records/{record_id}/missing-details")
@app.get("/api/records/{record_id}/missing-details")
def missing_details(record_id: int, platform: str = None):
    rec = get_record(record_id)
    if not rec:
        all_recs = list_records(limit=1)
        if all_recs:
            rec = all_recs[0]
        else:
            rec = {
                "id": record_id,
                "form_type": "prior_auth",
                "filename": "Prior_Auth_Form.pdf",
                "fields_json": "{}",
                "total_fields": 0,
                "missing_fields": 0
            }

    schema = FORM_SCHEMAS.get(rec.get("form_type", "prior_auth"), {})
    fields_dict = parse_fields_json(rec.get("fields_json"))
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

    if not missing_list:
        for k, label in schema_fields.items():
            guidance = get_field_guidance(k, label, platform_info)
            val_obj = fields_dict.get(k, {})
            val = val_obj.get("value", "") if isinstance(val_obj, dict) else str(val_obj)
            conf = val_obj.get("confidence", "missing") if isinstance(val_obj, dict) else "missing"
            missing_list.append({
                "key": k,
                "label": label,
                "value": val,
                "confidence": conf,
                "contact_help": guidance
            })

    return {
        "id": rec.get("id", record_id),
        "form_type": rec.get("form_type", "prior_auth"),
        "form_label": schema.get("label", rec.get("form_type", "Prior Authorization")),
        "filename": rec.get("filename"),
        "missing_fields": missing_list,
        "platform_detected": platform_info["name"],
        "platform_key": platform_info.get("key", "default"),
        "all_platforms": list_platforms()
    }


@app.post("/send-missing-email")
@app.post("/api/send-missing-email")
def send_missing_email(req: SendEmailRequest, request: Request):
    rec = get_record(req.record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")

    if not req.recipient_email or "@" not in req.recipient_email:
        raise HTTPException(status_code=400, detail="Invalid email address.")

    schema = FORM_SCHEMAS.get(rec.get("form_type", "prior_auth"), {})
    form_label = schema.get("label", rec.get("form_type", "Prior Authorization"))

    fields_dict = parse_fields_json(rec.get("fields_json"))
    missing_count = sum(
        1 for v in fields_dict.values()
        if (isinstance(v, dict) and v.get("confidence") == "missing") or not str(v.get("value") if isinstance(v, dict) else v).strip()
    )

    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        frontend_base = origin.rstrip("/").replace("/admin_dashboard.html", "").replace("/customer_dashboard.html", "")
    else:
        frontend_base = os.getenv("FRONTEND_URL", "https://healthcare-ne-zha.vercel.app").rstrip("/")

    form_link = f"{frontend_base}/fill_missing.html?record_id={req.record_id}"

    res = send_missing_fields_email(
        recipient_email=req.recipient_email,
        record_id=req.record_id,
        form_label=form_label,
        filename=rec.get("filename", ""),
        missing_count=missing_count,
        form_link=form_link
    )

    save_notification(req.record_id, req.recipient_email, form_link)
    res["link"] = form_link
    return res


@app.post("/submit-missing")
@app.post("/api/submit-missing")
def submit_missing(req: SubmitMissingRequest):
    rec = get_record(req.record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")

    fields_dict = parse_fields_json(rec.get("fields_json"))
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
        draft = generate_draft(rec.get("form_type", "prior_auth"), clean_fields)
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
@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="static"
    )
    app.mount(
        "/frontend",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="frontend"
    )

@app.get("/")
def read_root():
    return RedirectResponse(url="/static/index.html")

@app.get("/login.html")
@app.get("/static/login.html")
@app.get("/frontend/login.html")
def redirect_login():
    return RedirectResponse(url="/static/index.html")
