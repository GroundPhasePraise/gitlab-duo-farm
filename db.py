"""SQLite pool for gitlab accounts."""
import sqlite3
import threading
import time

import config

_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _lock, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                password TEXT,
                username TEXT,
                status TEXT DEFAULT 'created',
                stage TEXT DEFAULT '',
                group_url TEXT,
                pat TEXT,
                sms_number TEXT,
                proxy TEXT,
                error TEXT,
                created_at REAL,
                updated_at REAL
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS otp_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                kind TEXT,            -- captcha | sms | email_link
                request TEXT,         -- what operator/solver must answer
                answer TEXT,          -- filled by /solve or /sms-code
                status TEXT DEFAULT 'pending',  -- pending | answered | expired
                created_at REAL
            )""")


def add_account(email, password, username, proxy=""):
    import uuid
    now = time.time()
    if email == "pending":
        email = "pending-" + uuid.uuid4().hex[:8]
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO accounts (email,password,username,proxy,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (email, password, username, proxy, now, now))
        return cur.lastrowid


def set_stage(account_id, stage, status=None, error=None, **fields):
    now = time.time()
    sets = ["stage=?", "updated_at=?"]
    vals = [stage, now]
    if status is not None:
        sets.append("status=?"); vals.append(status)
    if error is not None:
        sets.append("error=?"); vals.append(error)
    for k, v in fields.items():
        if k in ("group_url", "pat", "sms_number", "email", "username", "proxy"):
            sets.append(f"{k}=?"); vals.append(v)
    vals.append(account_id)
    with _lock, _conn() as c:
        c.execute(f"UPDATE accounts SET {','.join(sets)} WHERE id=?", vals)


def get_account(account_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return dict(r) if r else None


def list_accounts(limit=100, status=None):
    with _conn() as c:
        if status:
            rows = c.execute("SELECT * FROM accounts WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM accounts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def enqueue_otp(account_id, kind, request):
    now = time.time()
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO otp_queue (account_id,kind,request,created_at) VALUES (?,?,?,?)",
            (account_id, kind, request, now))
        return cur.lastrowid


def answer_otp(queue_id, answer):
    with _lock, _conn() as c:
        c.execute("UPDATE otp_queue SET answer=?, status='answered' WHERE id=?", (answer, queue_id))


def wait_otp(queue_id, timeout=600, poll=2.0):
    """Block until operator/solver answers. Returns answer or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _conn() as c:
            r = c.execute("SELECT answer, status FROM otp_queue WHERE id=?", (queue_id,)).fetchone()
        if r and r["status"] == "answered" and r["answer"]:
            return r["answer"]
        time.sleep(poll)
    with _lock, _conn() as c:
        c.execute("UPDATE otp_queue SET status='expired' WHERE id=? AND status='pending'", (queue_id,))
    return None


def pending_otps():
    with _conn() as c:
        rows = c.execute("SELECT * FROM otp_queue WHERE status='pending' ORDER BY id DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]


init_db()
