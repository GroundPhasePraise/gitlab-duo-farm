if __name__ != "__main__" and not __import__("os").environ.get("GLAR_ALLOW_IMPORT"):
    raise ImportError(f"{__name__}: script-only module — run it directly (python {__file__})")
import os
"""login_code.py — rebuild aged-profile session for tnh4h77n5 after cookie wipe.
GitLab now gates login with an email verification code (new device). Flow:
IMAP snapshot ALL uids -> sign_in -> creds -> code page -> poll new uid -> extract 6-digit -> Verify -> save session.
No Zuora contact — safe during block cooldown."""
import imaplib
import json
import re
import sys
from pathlib import Path
import time

from playwright.sync_api import sync_playwright

import os as _os; sys.path.insert(0, str(Path(__file__).resolve().parent))
import gl_oauth_chrome as G

from paths import STAGE as _S, MAIL_POOL as _MP
STAGE = str(_S)
PROFILE = STAGE + "/chrome_reg_profile"
POOL = str(_MP)
USER = "tnh4h77n5"
import os as _os; PWD = _os.environ.get("GLAR_DEFAULT_PWD", "CHANGE_ME")
EMAIL = os.environ.get("GLAR_EMAIL_ADDR", "your-mailbox@t-online.de")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def mail_pass():
    for line in open(POOL, encoding="utf-8", errors="ignore"):
        if line.strip().startswith(EMAIL + ":"):
            return line.strip().split(":", 1)[1]
    return None


def conn():
    m = imaplib.IMAP4_SSL("imap.t-online.de", 993, timeout=20)
    m.login(EMAIL, mail_pass())
    m.select("INBOX")
    return m


def all_uids(m):
    typ, data = m.uid("search", None, "ALL")
    return set(data[0].split()) if data and data[0] else set()


def extract_code(raw):
    body = raw.split("\r\n\r\n", 1)[-1]
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"=\r?\n", "", text)
    text = re.sub(r"\s+", " ", text)
    mm = re.search(r"(?:following code|verification code|code is)[.\s:]*?(\d{6})", text, re.I)
    if mm:
        return mm.group(1)
    c = re.findall(r"\b\d{6}\b", text)
    return c[0] if c else None


def wait_new_code(old_uids, timeout=150):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            m = conn()
            new = all_uids(m) - old_uids
            for u in sorted(new, key=lambda x: int(x)):
                typ, msgd = m.uid("fetch", u, "(RFC822)")
                raw = msgd[0][1].decode("utf-8", "ignore")
                subj = re.search(r"^Subject: ([^\r\n]+)", raw, re.M)
                code = extract_code(raw)
                if code:
                    m.logout()
                    log(f"  code mail uid={u.decode()} subj={(subj.group(1)[:40] if subj else '?')} code={code}")
                    return code
            m.logout()
        except Exception as e:
            log("  imap err:", str(e)[:70])
        time.sleep(7)
    return None


with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        viewport={"width": 1440, "height": 1000}, locale="en-US",
        args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"])
    pg = ctx.new_page()
    pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    ok = False
    try:
        # snapshot inbox BEFORE triggering the code
        m0 = conn()
        old = all_uids(m0)
        m0.logout()
        log("inbox uids before:", len(old))
        # reach login form (generous CF retries)
        for attempt in range(4):
            pg.goto("https://gitlab.com/users/sign_in", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(4000)
            G.pass_cf(pg, 12)
            if pg.query_selector("#user_login"):
                log("login form reached, attempt", attempt)
                break
            log("no form, attempt", attempt, pg.url[:60])
        if not pg.query_selector("#user_login"):
            log("FATAL: CF wall")
            pg.screenshot(path=STAGE + "/lc_cfwall.png")
            sys.exit(2)
        pg.fill("#user_login", USER)
        pg.fill("#user_password", PWD)
        pg.click('input[name="commit"], button[type=submit]')
        pg.wait_for_timeout(6000)
        G.pass_cf(pg, 6)
        # detect the code page
        page_txt = pg.evaluate("() => document.body ? document.body.innerText.slice(0,400) : ''")
        log("after creds url:", pg.url[:70])
        code_field = pg.query_selector('#user_code, input[name="code"], input[name="otp_attempt"], input[autocomplete="one-time-code"], input[inputmode="numeric"]')
        need_code = code_field or "Verify code" in page_txt or "verification code" in page_txt.lower()
        if not need_code:
            who = pg.evaluate("""async () => { try { const r = await fetch('/api/v4/user'); const u = await r.json(); return u.username||''; } catch(e){ return ''; } }""")
            log("no code page; logged in as:", who)
            if who == USER:
                ok = True
        else:
            log("code page detected — fetching code from IMAP")
            pg.screenshot(path=STAGE + "/lc_codepage.png")
            code = wait_new_code(old, timeout=150)
            if not code:
                log("FATAL: no code in mailbox")
                pg.screenshot(path=STAGE + "/lc_nocode.png")
                sys.exit(3)
            log("code:", code)
            # fill code
            filled = False
            for sel in ['#user_code', 'input[name="code"]', 'input[name="otp_attempt"]',
                        'input[autocomplete="one-time-code"]', 'input[inputmode="numeric"]']:
                el = pg.query_selector(sel)
                if el:
                    el.fill(code)
                    log("filled into", sel)
                    filled = True
                    break
            if not filled:
                log("WARN: code input not found, trying any visible text input on form")
                el = pg.query_selector('form input[type="text"]:visible, form input:not([type]):visible')
                if el:
                    el.fill(code)
                    filled = True
            # click Verify code
            vpos = pg.evaluate("""() => {
                const b=[...document.querySelectorAll('button, input[type=submit], a')].find(x=>/verify code|verify|submit|continue/i.test((x.innerText||x.value||'').trim()) && x.offsetParent);
                if (!b) return null; const r=b.getBoundingClientRect();
                return {x:r.x+r.width/2, y:r.y+r.height/2, t:(b.innerText||b.value||'').trim().slice(0,30)};
            }""")
            log("verify btn:", vpos)
            if vpos:
                pg.mouse.click(vpos["x"], vpos["y"])
            pg.wait_for_timeout(8000)
            G.pass_cf(pg, 6)
            who = pg.evaluate("""async () => { try { const r = await fetch('/api/v4/user'); const u = await r.json(); return u.username||''; } catch(e){ return ''; } }""")
            log("after code, logged in as:", who, "url:", pg.url[:60])
            if who == USER:
                ok = True
        if ok:
            cookies = ctx.cookies("https://gitlab.com")
            sess = [c["value"] for c in cookies if c["name"] == "_gitlab_session"]
            cf = [c["value"][:16] for c in cookies if c["name"] == "cf_clearance"]
            log("session:", bool(sess), "cf_clearance:", bool(cf))
            if sess:
                json.dump({"username": USER, "session": sess[0], "ts": time.time()},
                          open(STAGE + "/tn_session_h4.json", "w"))
                log("saved tn_session_h4.json")
            pg.screenshot(path=STAGE + "/lc_ok.png")
    except Exception as e:
        log("ERR:", f"{type(e).__name__}: {str(e)[:150]}")
    finally:
        ctx.close()
log("LOGIN CODE", "OK" if ok else "FAILED")
