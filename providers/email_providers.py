"""Email providers: tempmail.lol (verified live 2026-09-19) + IMAP pool."""
import random
import re
import time

import httpx


class TempMailLol:
    """api.tempmail.lol/v2 - anon inbox, no registration. Verified: create returns address+token."""
    BASE = "https://api.tempmail.lol/v2"

    def __init__(self):
        self.client = httpx.Client(timeout=30, headers={"User-Agent": "glar/1.0"})
        self.address = None
        self.token = None

    def create_inbox(self):
        r = self.client.post(self.BASE + "/inbox/create")
        r.raise_for_status()
        d = r.json()
        self.address, self.token = d["address"], d["token"]
        return self.address

    def wait_for_email(self, sender_contains="gitlab", timeout=180, poll=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self.client.get(self.BASE + "/inbox", headers={"Authorization": "Bearer " + self.token})
            if r.status_code == 200:
                for msg in r.json().get("emails", []):
                    if sender_contains.lower() in (msg.get("from", "") + msg.get("subject", "")).lower():
                        return msg
            time.sleep(poll)
        return None

    @staticmethod
    def extract_links(text, pattern=r"https?://[^\s\"'<>]+"):
        return re.findall(pattern, text or "")


class ImapPool:
    """t-online.de pool from working_mails.txt (email:password lines). Random pick."""

    def __init__(self, path):
        self.path = path

    def take_account(self):
        with open(self.path, encoding="utf-8", errors="ignore") as f:
            lines = [l.strip() for l in f if l.strip() and ":" in l]
        email, password = random.choice(lines).split(":", 1)
        return email, password
