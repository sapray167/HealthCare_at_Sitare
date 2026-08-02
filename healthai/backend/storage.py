import time
from db import get_supabase

BUCKET_NAME = "documents"


def upload_file_to_storage(file_bytes: bytes, filename: str, user_email: str) -> str:
    """
    Uploads a file to Supabase Storage and returns its storage path.
    """

    sp = get_supabase()

    safe_filename = filename.replace(" ", "_")
    storage_path = f"{user_email}/{int(time.time())}_{safe_filename}"

    sp.storage.from_(BUCKET_NAME).upload(
        storage_path,
        file_bytes,
        {"content-type": "application/octet-stream"}
    )

    return storage_path


def download_file_from_storage(storage_path: str) -> bytes:
    """
    Downloads a file from Supabase Storage.
    """

    sp = get_supabase()

    return sp.storage.from_(BUCKET_NAME).download(storage_path)


def get_public_url(storage_path: str) -> str:
    """
    Returns the public URL of a stored file.
    """

    sp = get_supabase()

    return sp.storage.from_(BUCKET_NAME).get_public_url(storage_path)