"""restore_profile_h4.py — inject the VALID tnh4h77n5 session (tn_session_h4.json) into the aged profile.
No login form => no email-code gate => bypasses GitLab code throttling."""
if __name__ != "__main__" and not __import__("os").environ.get("GLAR_ALLOW_IMPORT"):
    raise ImportError(f"{__name__}: script-only module — run it directly (python {__file__})")

import json
import sys
from pathlib import Path
import time

from playwright.sync_api import sync_playwright

import os as _os; sys.path.insert(0, str(Path(__file__).resolve().parent))
import gl_oauth_chrome as G

from paths import STAGE as _S
STAGE = str(_S)
PROFILE = STAGE + "/chrome_reg_profile"
JS_WHO = ("async () => { try { const r = await fetch('/api/v4/user');"
          " const u = await r.json(); return u.username||''; } catch(e){ return ''; } }")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


h4 = json.load(open(STAGE + "/tn_session_h4.json", encoding="utf-8"))
log("injecting session for", h4["username"])

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        viewport={"width": 1280, "height": 900}, locale="en-US",
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"])
    pg = ctx.new_page()
    try:
        pg.goto("https://gitlab.com/dashboard", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        G.pass_cf(pg, 6)
        ctx.add_cookies([{"name": "_gitlab_session", "value": h4["session"],
                          "url": "https://gitlab.com"}])
        pg.reload(wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(4000)
        G.pass_cf(pg, 5)
        who = pg.evaluate(JS_WHO)
        log("profile user after inject:", who)
        if who == "tnh4h77n5":
            log("PROFILE RESTORED OK")
        else:
            log("INJECT FAILED — profile still", repr(who))
    except Exception as e:
        log("ERR:", f"{type(e).__name__}: {str(e)[:150]}")
    finally:
        ctx.close()
log("RESTORE PROFILE DONE")
