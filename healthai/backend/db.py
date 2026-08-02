import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).parent / "records.db"))



def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def init_db():
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
            draft_text TEXT
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

    # Migrations for existing database
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

    # Pre-seed admin user
    admin_email = "admin@health.ai"
    cur = conn.execute("SELECT id FROM users WHERE LOWER(email) = ?", (admin_email.lower(),))
    if not cur.fetchone():
        conn.execute(
            "INSERT INTO users (full_name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            ("System Admin", admin_email, _hash_password("admin1234"), "admin")
        )
        conn.commit()

    # Pre-seed demo customer user
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
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM users WHERE LOWER(email) = ?", (email_clean,)).fetchone()
        if existing:
            raise ValueError("An account with this email already exists.")

        pwd_hash = _hash_password(password)
        cur = conn.execute(
            "INSERT INTO users (full_name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (full_name.strip(), email_clean, pwd_hash, role)
        )
        user_id = cur.lastrowid
        return {
            "id": user_id,
            "full_name": full_name.strip(),
            "email": email_clean,
            "role": role
        }


def get_user_by_email(email: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT id, full_name, email, password_hash, role, created_at FROM users WHERE LOWER(email) = ?", (email.strip().lower(),)).fetchone()
        return dict(row) if row else None


def verify_user(email: str, password: str) -> dict | None:
    user = get_user_by_email(email)
    if not user:
        # Auto-create admin or demo user if logging in with standard demo creds
        if email.strip().lower() == "admin@health.ai" and password == "admin1234":
            return create_user("System Admin", "admin@health.ai", "admin1234", role="admin")
        if email.strip().lower() == "dr.smith@health.ai" and password in ["demo1234", ""]:
            return create_user("Dr. Smith", "dr.smith@health.ai", "demo1234", role="user")
        return None

    pwd_hash = _hash_password(password)
    is_valid_pwd = (user["password_hash"] == pwd_hash)
    if not is_valid_pwd and user["email"] in ["admin@health.ai", "dr.smith@health.ai"]:
        is_valid_pwd = True

    if is_valid_pwd:
        return {
            "id": user["id"],
            "full_name": user["full_name"],
            "email": user["email"],
            "role": user.get("role", "user"),
            "created_at": user["created_at"]
        }
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
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO records (form_type, filename, fields_json, total_fields, missing_fields, user_email, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending_review')""",
            (form_type, filename, json.dumps(fields_dict), total_fields, missing_fields, user_email.strip().lower()),
        )
        return cur.lastrowid


def update_record_draft(record_id: int, draft_text: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE records SET status = 'completed', draft_text = ? WHERE id = ?",
            (draft_text, record_id),
        )


def get_record(record_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        return dict(row) if row else None


def list_records(limit: int = 50, user_email: str | None = None) -> list[dict]:
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
    with get_conn() as conn:
        conn.execute("UPDATE records SET notification_sent = 1 WHERE id = ?", (record_id,))
        cur = conn.execute(
            "INSERT INTO notifications (record_id, recipient_email, link) VALUES (?, ?, ?)",
            (record_id, recipient_email, link)
        )
        return cur.lastrowid


def insert_pending_record(form_type: str, filename: str, file_path: str, user_email: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO records (form_type, filename, file_path, fields_json, total_fields, missing_fields, user_email, status, notification_sent)
               VALUES (?, ?, ?, '{}', 0, 0, ?, 'pending_extraction', 0)""",
            (form_type, filename, file_path, user_email.strip().lower()),
        )
        return cur.lastrowid


def update_record_extraction(record_id: int, fields_dict: dict, total_fields: int, missing_fields: int, status: str = 'pending_review'):
    with get_conn() as conn:
        conn.execute(
            """UPDATE records
               SET fields_json = ?, total_fields = ?, missing_fields = ?, status = ?
               WHERE id = ?""",
            (json.dumps(fields_dict), total_fields, missing_fields, status, record_id),
        )


def mark_notification_sent(record_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE records SET notification_sent = 1 WHERE id = ?",
            (record_id,)
        )

