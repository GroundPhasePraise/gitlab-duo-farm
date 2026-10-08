import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import STAGE as _S, MAIL_POOL as _MP
"""gl_code_gate.py — shared helpers: GitLab login with email-code gate via t-online IMAP."""
import imaplib
import json
import re
import socket
import time

JS_WHO = ("async () => { try { const r = await fetch('/api/v4/user');"
          " const u = await r.json(); return u.username||''; } catch(e){ return ''; } }")

TN4_ACC = {"user": os.environ.get("GLAR_TN4_USER","CHANGE_ME"), "pwd": os.environ.get("GLAR_TN4_PWD","CHANGE_ME"), "email": os.environ.get("GLAR_TN4_EMAIL","CHANGE_ME@t-online.de"), "mpwd": os.environ.get("GLAR_TN4_MPWD","CHANGE_ME")}
H4_ACC = {"user": os.environ.get("GLAR_H4_USER","CHANGE_ME"), "pwd": os.environ.get("GLAR_H4_PWD","CHANGE_ME"), "email": os.environ.get("GLAR_H4_EMAIL","CHANGE_ME@t-online.de"), "mpwd": os.environ.get("GLAR_H4_MPWD","CHANGE_ME")}

ACCOUNTS_JSON = str(_S / "gitlab_accounts.json")
MAIL_POOL = str(_MP)


def gate_for_user(pg, username, G):
    """Handle GitLab 'Verify your identity' login code gate for ANY account.
    Looks up email+mailbox password from gitlab_accounts.json (fallback: working_mails.txt).
    Returns True if passed / not needed; False if gate present but failed."""
    email = mpwd = None
    try:
        accs = json.load(open(ACCOUNTS_JSON, encoding="utf-8"))
        for a in accs:
            if a.get("username") == username and a.get("email"):
                email = a.get("email")
                mpwd = a.get("email_password")
                break
    except Exception:
        pass
    if not email:
        log(f"  gate: no email on file for {username}")
        return True
    if not mpwd:
        try:
            for line in open(MAIL_POOL, encoding="utf-8", errors="ignore"):
                if line.strip().startswith(email + ":"):
                    mpwd = line.strip().split(":", 1)[1]
                    break
        except Exception:
            pass
    if not mpwd:
        log(f"  gate: no mailbox password for {email}")
        return True
    acc = {"user": username, "pwd": "", "email": email, "mpwd": mpwd}
    return code_gate(pg, acc, G)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


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


def read_code_imap(email_addr, mpwd, max_age=45, tries=8, exclude_uids=None):
    """Newest 'Verify your identity' code. Returns (code, uid) or (None, None).
    exclude_uids: skip already-tried (stale/used) codes."""
    from email.utils import parsedate_to_datetime
    excl = exclude_uids or set()
    for t in range(tries):
        try:
            socket.setdefaulttimeout(40)
            m = imaplib.IMAP4_SSL("imap.t-online.de", 993)
            m.login(email_addr, mpwd)
            m.select("INBOX", readonly=True)
            typ, data = m.uid("search", None, '(FROM "gitlab")')
            uids = data[0].split() if data and data[0] else []
            try:
                m.close()
            except Exception:
                pass
            now = time.time()
            for u in sorted(uids, key=lambda x: int(x), reverse=True)[:4]:
                us = u.decode() if isinstance(u, bytes) else str(u)
                if us in excl:
                    continue
                try:
                    m2 = imaplib.IMAP4_SSL("imap.t-online.de", 993)
                    m2.login(email_addr, mpwd)
                    m2.select("INBOX", readonly=True)
                    typ, msgd = m2.uid("fetch", u, "(BODY.PEEK[])")
                    try:
                        m2.close()
                    except Exception:
                        pass
                    if not msgd or not msgd[0]:
                        continue
                    raw = msgd[0][1].decode("utf-8", "ignore")
                    subj = re.search(r"^Subject: ([^\r\n]+)", raw, re.M)
                    s = subj.group(1) if subj else ""
                    if "verify your identity" not in s.lower() and "verification" not in s.lower():
                        continue
                    date = re.search(r"^Date: ([^\r\n]+)", raw, re.M)
                    age = 9e9
                    if date:
                        try:
                            age = (now - parsedate_to_datetime(date.group(1)).timestamp()) / 60
                        except Exception:
                            pass
                    code = extract_code(raw)
                    if code and age < max_age:
                        log(f"  code {code} (age {age:.0f}m uid {us}) {email_addr}")
                        return code, us
                except Exception:
                    continue
        except Exception as e:
            log("  imap err:", str(e)[:60])
        time.sleep(10)
    return None, None


def click_text(pg, pattern, tags="button, input[type=submit], a"):
    pos = pg.evaluate("""([pat, tags]) => {
        let best=null;
        document.querySelectorAll(tags).forEach(el => {
            const t=(el.innerText||el.value||'').trim();
            if (!new RegExp(pat,'i').test(t) || !el.offsetParent) return;
            const r=el.getBoundingClientRect();
            if (r.width<2||r.height<2) return;
            const area=r.width*r.height;
            if (!best||area<best.area) best={x:r.x+r.width/2,y:r.y+r.height/2,t:t.slice(0,40)};
        });
        return best;
    }""", [pattern, tags])
    if pos:
        pg.mouse.click(pos["x"], pos["y"])
    return pos


def code_gate(pg, acc, G):
    """Pass the 'Verify your identity' gate. Retries with Resend on stale/used codes:
    GitLab codes are single-use; the newest mail may be an already-consumed code."""
    body = pg.evaluate("() => document.body ? document.body.innerText.slice(0,400).toLowerCase() : ''")
    cf = pg.query_selector('input[autocomplete="one-time-code"], #user_code, input[name="code"]')
    if not (cf and ("verify your identity" in body or "verification code" in body)):
        return True
    log("  code gate detected")
    tried = set()
    for rnd in range(3):
        if rnd > 0:
            # previous code was stale/used — force a fresh one
            if click_text(pg, "resend", "a, button"):
                log(f"  round {rnd}: resend clicked")
                pg.wait_for_timeout(3000)
            time.sleep(18)
        code, uid = read_code_imap(acc["email"], acc["mpwd"],
                                   max_age=45 if rnd == 0 else 8,
                                   tries=3 if rnd == 0 else 6,
                                   exclude_uids=tried)
        if not code:
            log(f"  round {rnd}: no fresh code")
            continue
        cf = pg.query_selector('input[autocomplete="one-time-code"], #user_code, input[name="code"]')
        if not cf:
            log("  gate input gone (passed or page changed)")
            break
        cf.fill("")
        cf.fill(code)
        click_text(pg, "verify code|^verify")
        pg.wait_for_timeout(7000)
        G.pass_cf(pg, 5)
        who = pg.evaluate(JS_WHO)
        log(f"  round {rnd}: code {code} -> user {who!r}")
        if who == acc["user"]:
            return True
        if uid:
            tried.add(uid)
    return False


def sign_out(pg, ctx, G):
    """Drop ONLY the _gitlab_session cookie, keeping cf_clearance (selective — never clear_cookies())."""
    dropped = False
    try:
        cookies = ctx.cookies("https://gitlab.com")
        keep = [c for c in cookies if c["name"] != "_gitlab_session"]
        had = len(cookies) != len(keep)
        ctx.clear_cookies()
        if keep:
            ctx.add_cookies(keep)
        dropped = had
        log(f"  session cookie dropped={had}, kept {len(keep)} cookies (cf_clearance preserved)")
    except Exception as e:
        log("  signout cookie err:", str(e)[:60])
    if not dropped:
        # fallback: navigate sign_out page
        try:
            pg.goto("https://gitlab.com/users/sign_out", wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(2500)
            G.pass_cf(pg, 4)
            btn = pg.query_selector('input[name="commit"], button[type=submit]')
            if btn:
                btn.click()
                pg.wait_for_timeout(3000)
        except Exception:
            pass
    # verify session gone
    try:
        pg.goto("https://gitlab.com/dashboard", wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(3000)
        G.pass_cf(pg, 4)
        who = pg.evaluate(JS_WHO)
        log("  after signout user:", repr(who))
    except Exception:
        pass


def login_as(pg, acc, G):
    for attempt in range(3):
        pg.goto("https://gitlab.com/users/sign_in", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3500)
        G.pass_cf(pg, 10)
        if pg.query_selector("#user_login"):
            pg.fill("#user_login", acc["user"])
            pg.fill("#user_password", acc["pwd"])
            pg.click('input[name="commit"], button[type=submit]')
            pg.wait_for_timeout(7000)
            G.pass_cf(pg, 6)
            code_gate(pg, acc, G)
        who = pg.evaluate(JS_WHO)
        if who == acc["user"]:
            log("logged in as", who)
            return True
        log(f"  attempt {attempt}: user={who!r} url={pg.url[:60]}")
    return False
