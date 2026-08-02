import os
import time
from pathlib import Path
from db import get_supabase

BUCKET_NAME = "documents"
UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


def upload_file_to_storage(file_bytes: bytes, filename: str, user_email: str) -> str:
    """
    Uploads a file to Supabase Storage or falls back seamlessly to local disk.
    """
    safe_filename = filename.replace(" ", "_")
    timestamp = int(time.time())
    storage_path = f"{user_email}/{timestamp}_{safe_filename}"

    sp = get_supabase()
    if sp:
        try:
            sp.storage.from_(BUCKET_NAME).upload(
                storage_path,
                file_bytes,
                {"content-type": "application/octet-stream"}
            )
            return storage_path
        except Exception as e:
            print(f"Supabase storage upload failed: {e}. Falling back to local disk storage.")

    # Fallback to local storage
    local_file = UPLOADS_DIR / f"{timestamp}_{safe_filename}"
    with open(local_file, "wb") as f:
        f.write(file_bytes)
    return str(local_file)


def download_file_from_storage(storage_path: str) -> bytes:
    """
    Downloads a file from Supabase Storage or reads from local disk.
    """
    sp = get_supabase()
    if sp and not os.path.exists(storage_path):
        try:
            return sp.storage.from_(BUCKET_NAME).download(storage_path)
        except Exception as e:
            print(f"Supabase storage download failed: {e}. Checking local disk.")

    if os.path.exists(storage_path):
        with open(storage_path, "rb") as f:
            return f.read()

    fname = os.path.basename(storage_path)
    local_file = UPLOADS_DIR / fname
    if local_file.exists():
        with open(local_file, "rb") as f:
            return f.read()

    raise ValueError(f"Could not locate file: {storage_path}")


def get_public_url(storage_path: str) -> str:
    """
    Returns the public URL of a stored file.
    """
    sp = get_supabase()
    if sp:
        try:
            return sp.storage.from_(BUCKET_NAME).get_public_url(storage_path)
        except Exception:
            pass
    return f"/static/uploads/{os.path.basename(storage_path)}"