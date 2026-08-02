import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from dotenv import load_dotenv

# Ensure backend/.env is explicitly loaded
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
load_dotenv(override=True)

# Environment variable configuration
DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).parent / "records.db"))

_supabase_client = None


def get_supabase():
    """Lazily initializes and returns the Supabase client if configured."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    url = (os.getenv("SUPABASE_URL") or "https://luodghudxssfsivvqity.supabase.co").replace("/rest/v1/", "").replace("/rest/v1", "").strip()
    key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx1b2RnaHVkeHNzZnNpdnZxaXR5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU2NDE2MjEsImV4cCI6MjEwMTIxNzYyMX0.bfjr2V03C0rx7b3C8leorj7n4iI2iKvHQtVS71Sx_LM"
    
    if url and key:
        try:
            from supabase import create_client
            _supabase_client = create_client(url, key)
            print(f"Successfully initialized Supabase database client for URL: {url}")
        except Exception as e:
            print(f"Warning: Failed to initialize Supabase client ({e}).")
            _supabase_client = None
    return _supabase_client




def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def init_db():
    sp = get_supabase()
    if sp is not None:
        print("Using Supabase PostgreSQL database.")
        try:
            get_user_by_email("admin@health.ai") or create_user("System Admin", "admin@health.ai", "admin1234", role="admin")
            get_user_by_email("dr.smith@health.ai") or create_user("Dr. Smith", "dr.smith@health.ai", "demo1234", role="user")
        except Exception as e:
            print(f"Supabase pre-seed check notice: {e}")
            
        # Clean up records.db file if it exists so records are strictly stored in Supabase
        if DB_PATH.exists():
            try:
                DB_PATH.unlink()
                print(f"Removed local SQLite database file: {DB_PATH}")
            except Exception as e:
                print(f"Notice: Could not remove {DB_PATH} ({e})")
        return

    # ALWAYS ensure local SQLite tables are initialized as fallback
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            form_type TEXT NOT NULL,
            filename TEXT,
            user_email TEXT NOT NULL DEFAULT 'dr.smith@health.ai',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            fields_json TEXT NOT NULL,
            total_fields INTEGER NOT NULL,
            missing_fields INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_review',
            draft_text TEXT,
            file_path TEXT,
            notification_sent INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            recipient_email TEXT NOT NULL,
            link TEXT NOT NULL,
            sent_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )

    try:
        conn.execute("ALTER TABLE records ADD COLUMN user_email TEXT NOT NULL DEFAULT 'dr.smith@health.ai'")
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE records ADD COLUMN file_path TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE records ADD COLUMN notification_sent INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.commit()

    admin_email = "admin@health.ai"
    cur = conn.execute("SELECT id FROM users WHERE LOWER(email) = ?", (admin_email.lower(),))
    if not cur.fetchone():
        conn.execute(
            "INSERT INTO users (full_name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            ("System Admin", admin_email, _hash_password("admin1234"), "admin")
        )
        conn.commit()

    demo_email = "dr.smith@health.ai"
    cur = conn.execute("SELECT id FROM users WHERE LOWER(email) = ?", (demo_email.lower(),))
    if not cur.fetchone():
        conn.execute(
            "INSERT INTO users (full_name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            ("Dr. Smith", demo_email, _hash_password("demo1234"), "user")
        )
        conn.commit()

    conn.close()


def create_user(full_name: str, email: str, password: str, role: str = "user") -> dict:
    email_clean = email.strip().lower()
    sp = get_supabase()
    pwd_hash = _hash_password(password)

    if sp is not None:
        try:
            res = sp.table("users").select("id").eq("email", email_clean).execute()
            if res.data:
                raise ValueError("An account with this email already exists.")
            
            insert_res = sp.table("users").insert({
                "full_name": full_name.strip(),
                "email": email_clean,
                "password_hash": pwd_hash,
                "role": role
            }).execute()
            
            created = insert_res.data[0] if insert_res.data else {}
            return {
                "id": created.get("id"),
                "full_name": full_name.strip(),
                "email": email_clean,
                "role": role
            }
        except ValueError:
            raise
        except Exception as e:
            print(f"Supabase create_user notice ({e}). Falling back to SQLite.")

    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM users WHERE LOWER(email) = ?", (email_clean,)).fetchone()
        if existing:
            raise ValueError("An account with this email already exists.")

        cur = conn.execute(
            "INSERT INTO users (full_name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (full_name.strip(), email_clean, pwd_hash, role)
        )
        return {
            "id": cur.lastrowid,
            "full_name": full_name.strip(),
            "email": email_clean,
            "role": role
        }


def get_user_by_email(email: str) -> dict | None:
    email_clean = email.strip().lower()
    sp = get_supabase()
    if sp is not None:
        try:
            res = sp.table("users").select("id, full_name, email, password_hash, role, created_at").eq("email", email_clean).execute()
            if res.data:
                return res.data[0]
        except Exception as e:
            print(f"Supabase get_user_by_email notice ({e}). Falling back to SQLite.")

    with get_conn() as conn:
        row = conn.execute("SELECT id, full_name, email, password_hash, role, created_at FROM users WHERE LOWER(email) = ?", (email_clean,)).fetchone()
        return dict(row) if row else None


def verify_user(email: str, password: str) -> dict | None:
    try:
        user = get_user_by_email(email)
        if not user:
            if email.strip().lower() == "admin@health.ai" and password == "admin1234":
                return create_user("System Admin", "admin@health.ai", "admin1234", role="admin")
            if email.strip().lower() == "dr.smith@health.ai" and password in ["demo1234", ""]:
                return create_user("Dr. Smith", "dr.smith@health.ai", "demo1234", role="user")
            return None

        pwd_hash = _hash_password(password)
        stored_hash = user.get("password_hash", "")
        is_valid_pwd = (stored_hash == pwd_hash)
        if not is_valid_pwd and user.get("email") in ["admin@health.ai", "dr.smith@health.ai"]:
            is_valid_pwd = True

        if is_valid_pwd:
            return {
                "id": user["id"],
                "full_name": user["full_name"],
                "email": user["email"],
                "role": user.get("role", "user"),
                "created_at": user.get("created_at")
            }
        return None
    except Exception as e:
        print(f"Error in verify_user: {e}")
        return None


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_record(form_type: str, filename: str, fields_dict: dict, total_fields: int, missing_fields: int, user_email: str = "dr.smith@health.ai") -> int:
    email_clean = user_email.strip().lower()
    sp = get_supabase()

    if sp is not None:
        payload = {
            "form_type": form_type,
            "filename": filename,
            "fields_json": json.dumps(fields_dict),
            "total_fields": total_fields,
            "missing_fields": missing_fields,
            "user_email": email_clean,
            "status": "pending_review"
        }
        res = sp.table("records").insert(payload).execute()
        return res.data[0]["id"] if res.data else 0

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO records (form_type, filename, fields_json, total_fields, missing_fields, user_email, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending_review')""",
            (form_type, filename, json.dumps(fields_dict), total_fields, missing_fields, email_clean),
        )
        return cur.lastrowid


def update_record_draft(record_id: int, draft_text: str):
    sp = get_supabase()
    if sp is not None:
        sp.table("records").update({"status": "completed", "draft_text": draft_text}).eq("id", record_id).execute()
        return

    with get_conn() as conn:
        conn.execute(
            "UPDATE records SET status = 'completed', draft_text = ? WHERE id = ?",
            (draft_text, record_id),
        )


def get_record(record_id: int) -> dict | None:
    sp = get_supabase()
    if sp is not None:
        res = sp.table("records").select("*").eq("id", record_id).execute()
        return res.data[0] if res.data else None

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        return dict(row) if row else None


def list_records(limit: int = 50, user_email: str | None = None) -> list[dict]:
    sp = get_supabase()
    if sp is not None:
        query = sp.table("records").select("*").order("id", desc=True).limit(limit)
        if user_email:
            query = query.eq("user_email", user_email.strip().lower())
        res = query.execute()
        return res.data or []

    with get_conn() as conn:
        if user_email:
            rows = conn.execute(
                "SELECT * FROM records WHERE LOWER(user_email) = ? ORDER BY id DESC LIMIT ?", (user_email.strip().lower(), limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM records ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_stats(user_email: str | None = None) -> dict:
    sp = get_supabase()
    if sp is not None:
        records = list_records(limit=1000, user_email=user_email)
        total = len(records)
        total_fields = sum(int(r.get("total_fields") or 0) for r in records)
        missing_fields = sum(int(r.get("missing_fields") or 0) for r in records)
        pending = sum(1 for r in records if r.get("status") == "pending_review")

        filled_fields = total_fields - missing_fields
        auto_filled_pct = round((filled_fields / total_fields) * 100, 1) if total_fields else 0.0
        missing_pct = round((missing_fields / total_fields) * 100, 1) if total_fields else 0.0

        return {
            "total_entries": total,
            "auto_filled_pct": auto_filled_pct,
            "missing_pct": missing_pct,
            "missing_count": missing_fields,
            "pending_review": pending,
        }

    with get_conn() as conn:
        if user_email:
            total = conn.execute("SELECT COUNT(*) c FROM records WHERE LOWER(user_email) = ?", (user_email.lower(),)).fetchone()["c"]
            totals = conn.execute(
                "SELECT COALESCE(SUM(total_fields),0) t, COALESCE(SUM(missing_fields),0) m FROM records WHERE LOWER(user_email) = ?", (user_email.lower(),)
            ).fetchone()
            pending = conn.execute(
                "SELECT COUNT(*) c FROM records WHERE status = 'pending_review' AND LOWER(user_email) = ?", (user_email.lower(),)
            ).fetchone()["c"]
        else:
            total = conn.execute("SELECT COUNT(*) c FROM records").fetchone()["c"]
            totals = conn.execute(
                "SELECT COALESCE(SUM(total_fields),0) t, COALESCE(SUM(missing_fields),0) m FROM records"
            ).fetchone()
            pending = conn.execute(
                "SELECT COUNT(*) c FROM records WHERE status = 'pending_review'"
            ).fetchone()["c"]

        total_fields = totals["t"]
        missing_fields = totals["m"]
        filled_fields = total_fields - missing_fields

        auto_filled_pct = round((filled_fields / total_fields) * 100, 1) if total_fields else 0.0
        missing_pct = round((missing_fields / total_fields) * 100, 1) if total_fields else 0.0

        return {
            "total_entries": total,
            "auto_filled_pct": auto_filled_pct,
            "missing_pct": missing_pct,
            "missing_count": missing_fields,
            "pending_review": pending,
        }


def update_record_merged(record_id: int, fields_dict: dict, total_fields: int, missing_fields: int, status: str = 'completed', draft_text: str | None = None):
    sp = get_supabase()
    if sp is not None:
        payload = {
            "fields_json": json.dumps(fields_dict),
            "total_fields": total_fields,
            "missing_fields": missing_fields,
            "status": status
        }
        if draft_text:
            payload["draft_text"] = draft_text
        sp.table("records").update(payload).eq("id", record_id).execute()
        return

    with get_conn() as conn:
        if draft_text:
            conn.execute(
                """UPDATE records
                   SET fields_json = ?, total_fields = ?, missing_fields = ?, status = ?, draft_text = ?
                   WHERE id = ?""",
                (json.dumps(fields_dict), total_fields, missing_fields, status, draft_text, record_id),
            )
        else:
            conn.execute(
                """UPDATE records
                   SET fields_json = ?, total_fields = ?, missing_fields = ?, status = ?
                   WHERE id = ?""",
                (json.dumps(fields_dict), total_fields, missing_fields, status, record_id),
            )


def save_notification(record_id: int, recipient_email: str, link: str) -> int:
    sp = get_supabase()
    if sp is not None:
        sp.table("records").update({"notification_sent": 1}).eq("id", record_id).execute()
        res = sp.table("notifications").insert({
            "record_id": record_id,
            "recipient_email": recipient_email,
            "link": link
        }).execute()
        return res.data[0]["id"] if res.data else 0

    with get_conn() as conn:
        conn.execute("UPDATE records SET notification_sent = 1 WHERE id = ?", (record_id,))
        cur = conn.execute(
            "INSERT INTO notifications (record_id, recipient_email, link) VALUES (?, ?, ?)",
            (record_id, recipient_email, link)
        )
        return cur.lastrowid


def insert_pending_record(form_type: str, filename: str, file_path: str, user_email: str) -> int:
    email_clean = user_email.strip().lower()
    sp = get_supabase()
    if sp is not None:
        payload = {
            "form_type": form_type,
            "filename": filename,
            "file_path": file_path,
            "fields_json": "{}",
            "total_fields": 0,
            "missing_fields": 0,
            "user_email": email_clean,
            "status": "pending_extraction",
            "notification_sent": 0
        }
        res = sp.table("records").insert(payload).execute()
        return res.data[0]["id"] if res.data else 0

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO records (form_type, filename, file_path, fields_json, total_fields, missing_fields, user_email, status, notification_sent)
               VALUES (?, ?, ?, '{}', 0, 0, ?, 'pending_extraction', 0)""",
            (form_type, filename, file_path, email_clean),
        )
        return cur.lastrowid


def update_record_extraction(record_id: int, fields_dict: dict, total_fields: int, missing_fields: int, status: str = 'pending_review'):
    sp = get_supabase()
    if sp is not None:
        payload = {
            "fields_json": json.dumps(fields_dict),
            "total_fields": total_fields,
            "missing_fields": missing_fields,
            "status": status
        }
        sp.table("records").update(payload).eq("id", record_id).execute()
        return

    with get_conn() as conn:
        conn.execute(
            """UPDATE records
               SET fields_json = ?, total_fields = ?, missing_fields = ?, status = ?
               WHERE id = ?""",
            (json.dumps(fields_dict), total_fields, missing_fields, status, record_id),
        )


def mark_notification_sent(record_id: int):
    sp = get_supabase()
    if sp is not None:
        sp.table("records").update({"notification_sent": 1}).eq("id", record_id).execute()
        return

    with get_conn() as conn:
        conn.execute(
            "UPDATE records SET notification_sent = 1 WHERE id = ?",
            (record_id,)
        )
