"""Gmail alias email provider: base+random@gmail.com, unlimited.
NOTE: Gmail strips +alias from To header -> match verification emails by subject+recency.
Verified IMAP 2026-09-19."""
import os
import datetime as dt
import email as email_lib
import email.utils as eut
import imaplib
import random
import re
import string
import time

HOST = "imap.gmail.com"
BASE_EMAIL = os.environ.get("GLAR_GMAIL_BASE", "yourbase@gmail.com")
BASE_USER = os.environ.get("GLAR_GMAIL_USER", "yourbase")
APP_PASS = os.environ.get("GLAR_GMAIL_APP_PASS", "")

VERIFY_KEYWORDS = ("confirm", "verify", "verification", "welcome")


class GmailAlias:
    def __init__(self, base=BASE_EMAIL, user=BASE_USER, app_pass=APP_PASS):
        self.base = base
        self.user = user
        self.app_pass = app_pass
        self.address = None
        self.suffix = None
        self.created_at = None

    def create_inbox(self):
        self.suffix = "gl" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        self.address = f"{self.user}+{self.suffix}@gmail.com"
        self.created_at = time.time()
        return self.address

    def _connect(self):
        m = imaplib.IMAP4_SSL(HOST)
        m.login(self.base, self.app_pass)
        m.select("INBOX")
        return m

    @staticmethod
    def _msg_date(msg):
        try:
            d = eut.parsedate_to_datetime(msg.get("Date"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d.timestamp()
        except Exception:
            return 0.0

    def _read_body(self, msg):
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    try:
                        body += part.get_payload(decode=True).decode("utf-8", "ignore")
                    except Exception:
                        pass
        else:
            try:
                body = msg.get_payload(decode=True).decode("utf-8", "ignore")
            except Exception:
                pass
        return body

    def wait_for_email(self, sender_contains="gitlab", timeout=300, poll=8):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                m = self._connect()
                t, d = m.search(None, "FROM", sender_contains)
                ids = d[0].split()
                for mid in reversed(ids[-25:]):
                    t, md = m.fetch(mid, "(RFC822)")
                    msg = email_lib.message_from_bytes(md[0][1])
                    ts = self._msg_date(msg)
                    if ts < (self.created_at or 0) - 60:
                        continue  # older than our signup — skip
                    to = str(msg.get("To", "")) + " " + str(msg.get("Delivered-To", ""))
                    subj = str(msg.get("Subject", "")).lower()
                    alias_hit = bool(self.suffix) and self.suffix in to
                    subj_hit = any(k in subj for k in VERIFY_KEYWORDS)
                    if alias_hit or subj_hit:
                        body = self._read_body(msg)
                        m.logout()
                        return {"from": str(msg.get("From", "")), "subject": str(msg.get("Subject", "")),
                                "body": body, "html": body}
                m.logout()
            except Exception as e:
                print("[gmail] poll error:", e)
            time.sleep(poll)
        return None

    @staticmethod
    def extract_links(text, pattern=r"https?://[^\s\"'<>]+"):
        return re.findall(pattern, text or "")
