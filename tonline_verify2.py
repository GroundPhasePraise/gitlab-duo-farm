"""tonline_verify2.py — controlled single-pass IDV completion:
login -> snapshot UIDs of SUBJECT="Confirm your email address" -> click Send a new code ->
poll for NEW uid (subject-scoped, no spam fetches) -> clean-extract code -> fill -> verify ->
probes + PAT + session cookie."""
import imaplib
import json
import re
import sys
from pathlib import Path
import time
from email.utils import parsedate_to_datetime

from playwright.sync_api import sync_playwright

import os as _os; sys.path.insert(0, str(Path(__file__).resolve().parent))
import gl_oauth_chrome as G

from paths import STAGE as _S, MAIL_POOL as _MP
STAGE = str(_S)
PROFILE = STAGE + "/chrome_reg_profile"
POOL = str(_MP)
USER = sys.argv[1] if len(sys.argv) > 1 else "tnh4h77n5"
PWD = sys.argv[2] if len(sys.argv) > 2 else "YOUR_PASSWORD"
EMAIL = sys.argv[3] if len(sys.argv) > 3 else "user@mailbox.t-online.de"
SUBJ = "Confirm your email address"


def log(*a):
    print(*a, flush=True)


def mail_pass():
    for l in open(POOL, encoding="utf-8", errors="ignore"):
        if l.strip().startswith(EMAIL + ":"):
            return l.strip().split(":", 1)[1]
    return None


def conn():
    m = imaplib.IMAP4_SSL("imap.t-online.de", 993, timeout=20)
    m.login(EMAIL, mail_pass())
    m.select("INBOX")
    return m


def code_uids(m):
    typ, data = m.uid("search", None, f'(SUBJECT "{SUBJ}")')
    return set(data[0].split()) if data and data[0] else set()


def extract_code(raw):
    body = raw.split("\r\n\r\n", 1)[-1]
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"=\r?\n", "", text)
    text = re.sub(r"\s+", " ", text)
    mm = re.search(r"(?:following code|verification code)[.\s:]*?(\d{6})", text, re.I)
    if mm:
        return mm.group(1)
    c = re.findall(r"\b\d{6}\b", text)
    return c[0] if c else None


def wait_new_code(old_uids, timeout=150):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            m = conn()
            new = code_uids(m) - old_uids
            for u in sorted(new):
                typ, msgd = m.uid("fetch", u, "(RFC822)")
                raw = msgd[0][1].decode("utf-8", "ignore")
                code = extract_code(raw)
                dm = re.search(r"^Date: ([^\r\n]+)", raw, re.M)
                dts = 0
                if dm:
                    try:
                        dts = parsedate_to_datetime(dm.group(1)).timestamp()
                    except Exception:
                        pass
                if code:
                    m.logout()
                    log(f"  new code mail uid={u.decode()} ts={int(dts)} code={code}")
                    return code
            m.logout()
        except Exception as e:
            log("  imap err:", str(e)[:70])
        time.sleep(7)
    return None


with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        viewport={"width": 1366, "height": 900}, locale="en-US",
        args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"])
    pg = ctx.new_page()
    pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    rec = {"ts": time.time(), "type": "tonline_verify2", "username": USER, "password": PWD, "email": EMAIL}
    try:
        # snapshot BEFORE resend
        m = conn()
        old = code_uids(m)
        m.logout()
        log("code-mail uids before:", len(old))
        pg.goto("https://gitlab.com/users/sign_in", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        G.pass_cf(pg, 8)
        if pg.query_selector("#user_login"):
            pg.fill("#user_login", USER)
            pg.fill("#user_password", PWD)
            pg.click('input[name="commit"], button[type=submit]')
            pg.wait_for_timeout(7000)
            G.pass_cf(pg, 6)
            from gl_code_gate import gate_for_user
            gate_for_user(pg, USER, G)
        log("after login:", pg.url[:90])
        if "identity_verification" not in pg.url:
            log("not redirected — checking IDV page directly")
            pg.goto("https://gitlab.com/users/identity_verification", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(6000)
            G.pass_cf(pg, 6)
            log("direct IDV url:", pg.url[:90])
        if "identity_verification" not in pg.url:
            rec["note"] = "IDV not required — account fully verified"
            log("NO IDV NEEDED:", pg.url[:90])
        else:
            clicked = pg.evaluate("""() => {
                const el = [...document.querySelectorAll('a,button')].find(x => /Send a new code/i.test(x.innerText||''));
                if (el) { el.click(); return true; }
                return false;
            }""")
            log("resend clicked:", clicked)
            pg.wait_for_timeout(3000)
            alert = pg.evaluate("""() => {
                const el = document.querySelector('.gl-alert, [role=alert], [data-testid=alert]');
                return el ? el.innerText.slice(0,80) : '';
            }""")
            log("alert:", alert)
            rec["resend_alert"] = alert
            code = wait_new_code(old)
            rec["code"] = code
            log("CODE:", code)
            if code:
                pg.fill('input[name="verification_code"]', code)
                pg.click('button:has-text("Verify email address"), button[type=submit]', timeout=6000)
                pg.wait_for_timeout(10000)
                G.pass_cf(pg, 6)
                log("after verify:", pg.url[:90])
                rec["after_verify"] = pg.url[:140]
                if "identity_verification" in pg.url:
                    rec["idv_body"] = pg.inner_text("body")[:350].replace("\n", " | ")
                    log("STILL IDV:", rec["idv_body"][:200])
                pg.screenshot(path=STAGE + "/tv2_verify.png")
        verified = "identity_verification" not in pg.url and "sign_in" not in pg.url
        if not verified:
            pg.goto("https://gitlab.com/dashboard", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(6000)
            G.pass_cf(pg, 4)
            verified = "identity_verification" not in pg.url and "sign_in" not in pg.url
        rec["verified"] = verified
        log("*** VERIFIED:", verified, "***")
        if verified:
            pg.goto("https://gitlab.com/-/duo_chat", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(7000)
            rec["duo_url"] = pg.url[:140]
            rec["duo_body"] = pg.inner_text("body")[:300].replace("\n", " | ")
            log("duo_chat:", pg.url[:80])
            log("duo body:", rec["duo_body"][:220])
            pg.screenshot(path=STAGE + "/tv2_duo.png")
            pg.goto("https://gitlab.com/-/trial_registrations/new", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(6000)
            rec["trial_url"] = pg.url[:140]
            rec["trial_body"] = pg.inner_text("body")[:300].replace("\n", " | ")
            log("trial:", pg.url[:80])
            log("trial body:", rec["trial_body"][:220])
            pg.screenshot(path=STAGE + "/tv2_trial.png")
            cookies = ctx.cookies("https://gitlab.com")
            sess = [c["value"] for c in cookies if c["name"] == "_gitlab_session"]
            if sess:
                rec["gitlab_session"] = sess[0]
                json.dump({"username": USER, "session": sess[0], "ts": time.time()},
                          open(STAGE + "/tn_session.json", "w"))
                log("SESSION SAVED")
            tok = G.create_pat(pg)
            if tok:
                un = G.verify_pat(tok)
                rec["pat"] = tok
                rec["pat_valid"] = bool(un)
                rec["gl_username"] = un
                log(f"*** PAT {tok[:16]}... valid={bool(un)} user={un} ***")
                try:
                    pool = json.load(open(STAGE + "/pat_pool.json", encoding="utf-8"))
                except Exception:
                    pool = []
                pool.append({"pat": tok, "username": un or USER, "ts": time.time(), "src": "tonline"})
                json.dump(pool, open(STAGE + "/pat_pool.json", "w", encoding="utf-8"), indent=1)
                log(f"PAT -> pool ({len(pool)})")
            else:
                log("PAT None")
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {str(e)[:150]}"
        log("ERR:", rec["error"])
    finally:
        ctx.close()
try:
    old = json.load(open(STAGE + "/gitlab_accounts.json", encoding="utf-8"))
except Exception:
    old = []
old.append(rec)
json.dump(old, open(STAGE + "/gitlab_accounts.json", "w", encoding="utf-8"), indent=1)
log("RESULT:", json.dumps({k: v for k, v in rec.items() if k not in ('gitlab_session', 'pat', 'idv_body')}, ensure_ascii=False)[:300])
log("TV2 DONE")
