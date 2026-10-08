"""2nd-no.com (2nr.pl) free Polish SMS numbers — FULL AUTOMATION.
Flow: register(tempmail) -> confirm email -> login -> turnstile(YesCaptcha) -> reserve number -> poll SMS.
API: POST https://2no.pl/ JSON-RPC, auth x-auth-token (sessionStorage 2NR-TOKEN).
Free: 2 accounts/email domain?, number_limit=3 per account, 3-day validity, extended on SMS receipt.
Verified live 2026-09-20: number +48 729756039 reserved, success:true."""
import json
import random
import re
import string
import time

import httpx
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TM_BASE = "https://api.tempmail.lol/v2"
SITEKEY = "0x4AAAAAAAh6YYTPTzEcN3Ep"   # from 2nd bundle index-ff34328d.js
API = "https://2no.pl/"
from paths import STAGE as _S
STATE_FILE = str(_S / "2ndno_state.json")


class TempMail:
    def __init__(self):
        self.c = httpx.Client(timeout=30)
        self.address = None
        self.token = None

    def create(self):
        d = self.c.post(TM_BASE + "/inbox/create").json()
        self.address, self.token = d["address"], d["token"]
        return self.address

    def wait_email(self, sender=None, timeout=180, poll=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self.c.get(TM_BASE + "/inbox", params={"token": self.token})
            if r.status_code == 200:
                for m in r.json().get("emails", []):
                    if sender is None or sender.lower() in (str(m.get("from", "")) + str(m.get("subject", ""))).lower():
                        return m
            time.sleep(poll)
        return None


class SecondNo:
    """Browser-driven 2nd-no.com client (Cloudflare only passes inside browser)."""

    def __init__(self, solver=None):
        self._pw = None
        self._browser = None
        self._pg = None
        self.solver = solver

    # ---- lifecycle ----
    def _start(self):
        if self._pg is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=False, channel="chrome", args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--window-position=2400,2400"])
            ctx = self._browser.new_context(user_agent=UA, locale="en-US")
            self._pg = ctx.new_page()
            self._pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        return self._pg

    def close(self):
        try:
            self._browser.close()
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass
        self._pg = None

    # ---- api via browser context ----
    def _call(self, id_, query=None):
        body = {"id": id_}
        if query is not None:
            body["query"] = query
        pg = self._start()
        res = pg.evaluate("""async (body) => {
            const tok = sessionStorage.getItem('2NR-TOKEN');
            const r = await fetch('https://2no.pl/', {method:'POST',
                headers:{'Content-Type':'application/json','x-auth-token':tok||''},
                body: JSON.stringify(body)});
            return await r.text();
        }""", body)
        try:
            return json.loads(res)
        except Exception:
            return {"raw": res[:200]}

    # ---- steps ----
    def register(self, password=None):
        pg = self._start()
        tm = TempMail()
        email = tm.create()
        pwd = password or ("Nx" + "".join(random.choices(string.ascii_letters, k=8)) + "7!q")
        pg.goto("https://2nd-no.com/auth/register", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3500)
        ok = pg.evaluate("""(args) => {
            const setVal = (el, v) => { const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value').set;
                setter.call(el, v); el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true})); };
            const inputs = Array.from(document.querySelectorAll('input'));
            const txt = inputs.find(i => i.type === 'text' || i.type === 'email');
            const pws = inputs.filter(i => i.type === 'password');
            const cb = inputs.find(i => i.type === 'checkbox');
            if (!txt || pws.length < 2) return 'inputs missing';
            setVal(txt, args[0]); setVal(pws[0], args[1]); setVal(pws[1], args[1]);
            if (cb && !cb.checked) cb.click();
            return 'ok';
        }""", [email, pwd])
        if ok != "ok":
            raise RuntimeError(f"register fill failed: {ok}")
        pg.evaluate("() => document.querySelector('button[type=submit]').click()")
        pg.wait_for_timeout(6000)
        # confirm email
        msg = tm.wait_email(sender="2nr", timeout=180)
        if not msg:
            msg = tm.wait_email(timeout=60)
        link = None
        if msg:
            body = (msg.get("body") or "") + (msg.get("html") or "")
            links = re.findall(r"https?://[^\s\"'<>]+", body)
            link = next((l for l in links if "create-account" in l or "confirm" in l), None)
        if not link:
            raise RuntimeError("no confirmation link")
        pg.goto(link, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        self.creds = {"email": email, "password": pwd}
        return self.creds

    def login(self, email, password):
        pg = self._start()
        pg.goto("https://2nd-no.com/auth/login", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        pg.evaluate("""(args) => {
            const setVal = (el, v) => { const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value').set;
                setter.call(el, v); el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true})); };
            const inputs = Array.from(document.querySelectorAll('input'));
            setVal(inputs.find(i => i.type === 'email' || i.type === 'text'), args[0]);
            setVal(inputs.find(i => i.type === 'password'), args[1]);
        }""", [email, password])
        pg.wait_for_timeout(500)
        pg.evaluate("() => document.querySelector('button[type=submit]').click()")
        pg.wait_for_url("**/app/**", timeout=25000)
        pg.wait_for_timeout(3000)
        self.creds = {"email": email, "password": password}
        return True

    def get_number(self):
        """Reserve a free Polish number. Solves Turnstile via YesCaptcha."""
        rnd = self._call(310)
        result = rnd.get("result") or []
        if not result:
            raise RuntimeError(f"no free number: {str(rnd)[:120]}")
        num_id, number = result[0]["id"], result[0]["number"]
        ts = ""
        if rnd.get("captcha") == "turnstile" and self.solver:
            ts = self.solver.turnstile(SITEKEY, "https://2nd-no.com/")
        res = self._call(301, {"number_id": num_id, "name": "gl", "color": "Red",
                               "right_to_transfer_number": True, "response_key": ts})
        if not res.get("success"):
            raise RuntimeError(f"reserve failed: {str(res)[:150]}")
        my = self._call(311, {"offset": 0, "limit": 10})
        entry = (my.get("result") or [{}])[0]
        out = {"number": number, "full": "+48" + number, "number_id": num_id,
               "user_number_id": entry.get("id"), "expires": entry.get("reservation_to")}
        self._save(out)
        return out

    def _save(self, info):
        state = {}
        try:
            state = json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            state = {"accounts": []}
        acc = dict(self.creds or {})
        acc.update(info)
        state.setdefault("accounts", []).append(acc)
        json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), indent=1)

    def read_sms(self, phone, number_id, timeout=300, poll=8):
        """Poll SMS for a reserved number. NOTE: 2no.pl API 415 needs phone=STRING and
        number_id=INT; actual messages arrive under badges.messages (data.messages stays empty)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            d = self._call(415, {"phone": str(phone), "number_id": int(number_id),
                                 "limit": 25, "offset": 0})
            msgs = []
            for b in (d.get("badges") or {}).get("messages") or []:
                msgs.extend(b.get("messages") or [])
            msgs.extend((d.get("data", {}) or {}).get("messages") or [])
            msgs.extend(d.get("result") or [])
            if msgs:
                return msgs
            time.sleep(poll)
        return []

    def wait_otp(self, phone, number_id, timeout=300, poll=8, digits=(4, 8)):
        """Wait for first SMS and extract the OTP code (GitLab codes are 6-7 digits)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for m in self.read_sms(phone, number_id, timeout=poll * 2):
                text = m.get("text") or m.get("body") or ""
                mm = re.search(r"code is (\d{4,8})", text)
                if mm:
                    return mm.group(1), text
                for n in digits:
                    mm = re.search(rf"\b(\d{{{n}}})\b", text)
                    if mm:
                        return mm.group(1), text
            time.sleep(poll)
        return None, None


def full_cycle(count=1, solver=None):
    """Register fresh account(s) and grab number(s). Returns list of dicts."""
    if solver is None:
        import os
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from providers.captcha import get_solver
        solver = get_solver()
    out = []
    for _ in range(count):
        s = SecondNo(solver=solver)
        try:
            creds = s.register()
            s.login(creds["email"], creds["password"])
            s.get_number()
            out.append({**creds, **json.load(open(STATE_FILE))["accounts"][-1]})
        except Exception as e:
            out.append({"error": str(e)[:150]})
        finally:
            s.close()
    return out


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    for r in full_cycle(n):
        print(json.dumps(r, ensure_ascii=False))
