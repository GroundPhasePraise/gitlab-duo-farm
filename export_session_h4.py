"""export_session_h4.py — export fresh tnh4h77n5 _gitlab_session cookie from aged profile to tn_session.json."""
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

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        viewport={"width": 1280, "height": 900}, locale="en-US",
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"])
    pg = ctx.new_page()
    try:
        pg.goto("https://gitlab.com/dashboard", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3500)
        G.pass_cf(pg, 6)
        who = pg.evaluate("""async () => { try { const r = await fetch('/api/v4/user'); const u = await r.json(); return u.username||''; } catch(e){ return ''; } }""")
        print("session user:", who, flush=True)
        if who != "tnh4h77n5":
            print("FATAL: wrong user in profile", flush=True)
            sys.exit(1)
        cookies = ctx.cookies("https://gitlab.com")
        sess = [c["value"] for c in cookies if c["name"] == "_gitlab_session"]
        if sess:
            json.dump({"username": who, "session": sess[0], "ts": time.time()},
                      open(STAGE + "/tn_session.json", "w"))
            print("SAVED tn_session.json (fresh tnh4h77n5)", flush=True)
        else:
            print("NO SESSION COOKIE", flush=True)
    except Exception as e:
        print("ERR:", f"{type(e).__name__}: {str(e)[:150]}", flush=True)
    finally:
        ctx.close()
print("EXPORT SESSION DONE", flush=True)
