"""tonline_signup.py — GitLab signup with a REAL t-online.de ISP mailbox (gmail +alias pattern
is blocked by GitLab since ~Sep 21). Firefox/Juggler on machine IP.
Flow: signup -> (IDV? email code/link via t-online IMAP) -> landing check -> phone step? ->
if usable: trial -> PAT -> save. Also records _gitlab_session cookie for the gateway pool."""
if __name__ != "__main__" and not __import__("os").environ.get("GLAR_ALLOW_IMPORT"):
    raise ImportError(f"{__name__}: script-only module — run it directly (python {__file__})")

import imaplib
import json
import random
import re
import string
import sys
from pathlib import Path
import time

import os as _os; sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.sync_api import sync_playwright

from paths import STAGE as _S, MAIL_POOL as _MP
STAGE = str(_S)
PROFILE = STAGE + "/chrome_ff_profile"
POOL = str(_MP)
OUT = STAGE + "/gitlab_accounts.json"


def log(*a):
    print(*a, flush=True)


def rnd(n):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def take_mail():
    lines = [l.strip() for l in open(POOL, encoding="utf-8", errors="ignore")
             if l.strip() and ":" in l and not l.startswith("#")]
    email, pwd = random.choice(lines).split(":", 1)
    return email.strip(), pwd.strip()


def tonline_read(email, pwd, timeout=200):
    """Poll t-online IMAP for GitLab mail. Returns (code, links, subject)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            m = imaplib.IMAP4_SSL("imap.t-online.de", 993, timeout=25)
            m.login(email, pwd)
            m.select("INBOX")
            typ, data = m.search(None, "ALL")
            ids = data[0].split()[-6:] if data and data[0] else []
            for i in reversed(ids):
                typ, msgd = m.fetch(i, "(RFC822)")
                raw = msgd[0][1].decode("utf-8", "ignore")
                if "gitlab" not in raw.lower():
                    continue
                subj = ""
                sm = re.search(r"Subject: ([^\r\n]+)", raw)
                if sm:
                    subj = sm.group(1)
                body = raw.split("\r\n\r\n", 1)[-1]
                text = re.sub(r"<[^>]+>", " ", body)
                text = re.sub(r"=\r?\n", "", text)
                text = re.sub(r"\s+", " ", text)
                mm = re.search(r"(?:following code|verification code|code is)[.\s:]*?(\d{6})", text, re.I)
                codes = [mm.group(1)] if mm else re.findall(r"\b\d{6}\b", text)
                links = re.findall(r"https://gitlab\.com/users/confirmation[^\s\"'<>]+", raw)
                if not links:
                    links = re.findall(r"https://gitlab\.com/[^\s\"'<>]*token[^\s\"'<>]*", raw)
                m.logout()
                return (codes[0] if codes else None), links, subj
            m.logout()
        except Exception as e:
            log("  imap err:", str(e)[:60])
        time.sleep(8)
    return None, [], ""


username = "tn" + rnd(7)
password = "".join(random.choices(string.ascii_letters, k=10)) + random.choice("!#?9") + rnd(3)
email, epwd = take_mail()
rec = {"ts": time.time(), "type": "tonline_signup", "username": username, "password": password,
       "email": email, "email_password": epwd}
log("signup:", username, "email:", email)

with sync_playwright() as pw:
    ctx = pw.firefox.launch_persistent_context(
        PROFILE, headless=False,
        viewport={"width": 1366, "height": 900}, locale="en-US")
    pg = ctx.pages[0] if ctx.pages else ctx.new_page()
    pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    try:
        pg.goto("https://gitlab.com/users/sign_up", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(4000)
        log("sign_up:", pg.url[:70])
        pg.fill('input[name="new_user[first_name]"]', "Artur")
        pg.fill('input[name="new_user[last_name]"]', "Meier")
        pg.fill('input[name="new_user[username]"]', username)
        pg.fill('input[name="new_user[email]"]', email)
        pg.fill('input[name="new_user[password]"]', password)
        pg.wait_for_timeout(1200)
        challenged = pg.evaluate("""() => {
            const ifr=[...document.querySelectorAll('iframe')].some(f=>(f.src||'').includes('arkoselabs'));
            return !!window.arkoseEnforcement || ifr;
        }""")
        rec["arkose_at_signup"] = challenged
        log("arkose at form:", challenged)
        pg.click('button:has-text("Continue"), input[type="submit"]', timeout=8000)
        pg.wait_for_timeout(9000)
        rec["landed"] = pg.url[:140]
        log("LANDED:", pg.url)
        pg.screenshot(path=STAGE + "/tn_land.png")
        # email-not-allowed error?
        errs = pg.evaluate("""() => {
            const out=[]; document.querySelectorAll('.error, .gl-alert, .devise-errors, .flash-error').forEach(e=>{const t=(e.innerText||'').trim().slice(0,140); if(t)out.push(t);}); return out.slice(0,4);
        }""")
        if errs:
            rec["form_errors"] = errs
            log("FORM ERRORS:", errs)
        # read the confirmation/IDV mail
        log("reading t-online mailbox (200s)...")
        code, links, subj = tonline_read(email, epwd)
        rec["mail_subject"] = subj
        rec["mail_code"] = code
        rec["mail_links"] = links[:2]
        log(f"mail: subj={subj[:60]!r} code={code} links={len(links)}")
        if code and "identity_verification" in pg.url:
            log("IDV email-code step — filling")
            pg.fill('input[name="verification_code"]', code)
            pg.click('button:has-text("Verify"), button[type=submit]', timeout=6000)
            pg.wait_for_timeout(8000)
            rec["after_email"] = pg.url[:140]
            b2 = pg.inner_text("body")[:300].replace("\n", " | ")
            rec["phone_step"] = "Phone" in b2
            log("after email:", pg.url[:90], "| phone step:", rec["phone_step"])
            pg.screenshot(path=STAGE + "/tn_idv.png")
        elif links:
            log("confirmation LINK flow — opening first link")
            pg.goto(links[0], wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(7000)
            rec["after_link"] = pg.url[:140]
            log("after link:", pg.url[:90])
            pg.screenshot(path=STAGE + "/tn_link.png")
        # usability probe: are we logged in & not IDV-blocked?
        pg.goto("https://gitlab.com/-/profile", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(5000)
        rec["profile_url"] = pg.url[:140]
        logged = "sign_in" not in pg.url and "identity_verification" not in pg.url
        rec["logged_in"] = logged
        log("profile:", pg.url[:90], "| logged:", logged)
        if logged:
            pg.goto("https://gitlab.com/-/duo_chat", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(7000)
            rec["duo_url"] = pg.url[:140]
            rec["duo_body"] = pg.inner_text("body")[:300].replace("\n", " | ")
            log("duo_chat:", pg.url[:90])
            log("duo body:", rec["duo_body"][:220])
            pg.screenshot(path=STAGE + "/tn_duo.png")
            # grab session cookie for gateway
            cookies = ctx.cookies("https://gitlab.com")
            sess = [c["value"] for c in cookies if c["name"] == "_gitlab_session"]
            if sess:
                rec["gitlab_session"] = sess[0]
                log("session cookie captured:", sess[0][:20] + "...")
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {str(e)[:150]}"
        log("ERR:", rec["error"])
    finally:
        ctx.close()

import httpx
try:
    r = httpx.get(f"https://gitlab.com/api/v4/users?username={username}", timeout=20)
    rec["api_exists"] = r.json()
    log("API exists:", r.json())
except Exception as e:
    log("api err", str(e)[:60])
try:
    old = json.load(open(OUT, encoding="utf-8"))
except Exception:
    old = []
old.append(rec)
json.dump(old, open(OUT, "w", encoding="utf-8"), indent=1)
log("RESULT SAVED:", username)
log("TONLINE SIGNUP DONE")
