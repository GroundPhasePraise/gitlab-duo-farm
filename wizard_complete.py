"""wizard_complete.py — complete GitLab onboarding welcome wizard with REAL interactions:
fill text inputs, select every required dropdown (first viable option), Continue through steps
until out of /users/sign_up/welcome. Then create PAT + probe duo/trial + save session."""
import json
import random
import string
import sys
from pathlib import Path
import time

from playwright.sync_api import sync_playwright

import os as _os; sys.path.insert(0, str(Path(__file__).resolve().parent))
import gl_oauth_chrome as G

from paths import STAGE as _S
STAGE = str(_S)
PROFILE = STAGE + "/chrome_reg_profile"
USER = sys.argv[1] if len(sys.argv) > 1 else "tnh4h77n5"
PWD = sys.argv[2] if len(sys.argv) > 2 else "YOUR_PASSWORD"


def log(*a):
    print(*a, flush=True)


def fill_texts(pg):
    n = 0
    for inp in pg.query_selector_all('input[type="text"]:not([readonly]), input:not([type]):not([readonly])'):
        try:
            if inp.is_visible() and not (inp.input_value() or "").strip():
                inp.click()
                inp.fill("Nova" + str(random.randint(100, 999)))
                n += 1
        except Exception:
            pass
    return n


def select_dropdowns(pg):
    """Open each gl-dropdown whose toggle shows a placeholder, pick first option."""
    n = 0
    for _ in range(10):
        toggles = pg.query_selector_all('[data-testid="dropdown-menu-toggle"], button.gl-button.dropdown-menu-toggle, [aria-haspopup="listbox"]')
        target = None
        for t in toggles:
            try:
                if not t.is_visible():
                    continue
                txt = (t.inner_text() or "").strip().lower()
                if "select" in txt or "please" in txt or not txt:
                    target = t
                    break
            except Exception:
                continue
        if not target:
            break
        try:
            target.click()
            pg.wait_for_timeout(900)
            opt = None
            for sel in ('[role="option"]', '.dropdown-item', '[data-testid="dropdown-item"]', "li.gl-dropdown-item"):
                opts = pg.query_selector_all(sel)
                for o in opts:
                    try:
                        if o.is_visible():
                            opt = o
                            break
                    except Exception:
                        continue
                if opt:
                    break
            if opt:
                otxt = (opt.inner_text() or "").strip()[:30]
                opt.click()
                pg.wait_for_timeout(700)
                n += 1
                log(f"    dropdown selected: {otxt!r}")
            else:
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(300)
                break
        except Exception as e:
            log("    dropdown err:", str(e)[:60])
            break
    return n


with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        viewport={"width": 1366, "height": 900}, locale="en-US",
        args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"])
    pg = ctx.new_page()
    pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    rec = {"ts": time.time(), "type": "wizard_complete", "username": USER}
    try:
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
        for step in range(10):
            if "welcome" not in pg.url:
                break
            tf = fill_texts(pg)
            dd = select_dropdowns(pg)
            cont = pg.evaluate("""() => {
                const b = [...document.querySelectorAll('button')].find(x => /^Continue$/i.test((x.innerText||'').trim()) && x.offsetParent);
                if (b && !b.disabled) { b.click(); return 'clicked'; }
                if (b) return 'disabled';
                const s = [...document.querySelectorAll('button,a')].find(x => /^(Skip|Next|Finish|Create|Get started|Submit)/i.test((x.innerText||'').trim()) && x.offsetParent);
                if (s) { s.click(); return 'alt:' + s.innerText.trim(); }
                return null;
            }""")
            log(f"  step {step}: texts={tf} dropdowns={dd} continue={cont!r} url={pg.url[:60]}")
            pg.wait_for_timeout(4500)
            G.pass_cf(pg, 3)
            pg.screenshot(path=STAGE + f"/wz_{step}.png")
        rec["after_wizard"] = pg.url[:140]
        log("AFTER WIZARD:", pg.url[:90])
        if "welcome" in pg.url:
            body = pg.inner_text("body")[:300].replace("\n", " | ")
            rec["wizard_body"] = body
            log("still wizard, body:", body[:200])
        # PAT
        tok = G.create_pat(pg)
        rec["pat"] = tok
        if tok:
            un = G.verify_pat(tok)
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
        # duo probe
        pg.goto("https://gitlab.com/-/duo_chat", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(8000)
        G.pass_cf(pg, 4)
        rec["duo_url"] = pg.url[:140]
        rec["duo_body"] = pg.inner_text("body")[:400].replace("\n", " | ")
        log("duo_chat:", pg.url[:80])
        log("duo body:", rec["duo_body"][:260])
        pg.screenshot(path=STAGE + "/wz_duo.png")
        # trial probe
        pg.goto("https://gitlab.com/-/trial_registrations/new", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(6000)
        rec["trial_url"] = pg.url[:140]
        rec["trial_body"] = pg.inner_text("body")[:400].replace("\n", " | ")
        log("trial:", pg.url[:80])
        log("trial body:", rec["trial_body"][:260])
        pg.screenshot(path=STAGE + "/wz_trial.png")
        cookies = ctx.cookies("https://gitlab.com")
        sess = [c["value"] for c in cookies if c["name"] == "_gitlab_session"]
        if sess:
            rec["gitlab_session"] = sess[0]
            json.dump({"username": USER, "session": sess[0], "ts": time.time()},
                      open(STAGE + "/tn_session.json", "w"))
            log("SESSION SAVED")
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
log("RESULT:", json.dumps({k: v for k, v in rec.items() if k not in ('gitlab_session', 'pat', 'wizard_body')}, ensure_ascii=False)[:400])
log("WIZARD COMPLETE DONE")
