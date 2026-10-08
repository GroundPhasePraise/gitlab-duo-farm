"""trial_activate.py — fill /-/trials/new (group, company, country dropdown), Activate my trial,
watch for arkose/IDV/activation. If Ultimate activates: probe duo_chat, create PAT properly,
save PAT + session to pool files for the gateway."""
if __name__ != "__main__" and not __import__("os").environ.get("GLAR_ALLOW_IMPORT"):
    raise ImportError(f"{__name__}: script-only module — run it directly (python {__file__})")

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


def rnd(n):
    return "".join(random.choices(string.ascii_lowercase, k=n))


def pick_country(pg, want="Germany"):
    for t in pg.query_selector_all('[data-testid="dropdown-menu-toggle"], button[aria-haspopup="listbox"], .gl-dropdown button, button.gl-button'):
        try:
            if not t.is_visible():
                continue
            txt = (t.inner_text() or "").strip().lower()
            if "select a country" in txt or "country" in txt:
                t.click()
                pg.wait_for_timeout(900)
                # type to filter if searchable
                try:
                    pg.keyboard.type(want, delay=30)
                    pg.wait_for_timeout(900)
                except Exception:
                    pass
                for sel in ('[role="option"]', ".dropdown-item", '[data-testid="dropdown-item"]'):
                    for o in pg.query_selector_all(sel):
                        try:
                            if o.is_visible() and want.lower() in (o.inner_text() or "").lower():
                                o.click()
                                pg.wait_for_timeout(600)
                                return True
                        except Exception:
                            continue
                # fallback: first option
                for sel in ('[role="option"]', ".dropdown-item"):
                    for o in pg.query_selector_all(sel):
                        try:
                            if o.is_visible():
                                o.click()
                                pg.wait_for_timeout(600)
                                return True
                        except Exception:
                            continue
        except Exception:
            continue
    return False


resp_log = []
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        viewport={"width": 1366, "height": 900}, locale="en-US",
        args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"])
    pg = ctx.new_page()
    pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

    def on_resp(r):
        try:
            u = r.url
            if any(k in u for k in ("trial", "identity", "arkose", "subscription")) and "assets" not in u and ".js" not in u and ".css" not in u:
                resp_log.append(f"{r.request.method} {r.status} {u[:110]}")
        except Exception:
            pass

    pg.on("response", on_resp)
    rec = {"ts": time.time(), "type": "trial_activate", "username": USER}
    try:
        pg.goto("https://gitlab.com/-/trials/new", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(4000)
        G.pass_cf(pg, 6)
        # API-based auth check: URL heuristic misses the /-/trial_registrations/new marketing redirect
        who = pg.evaluate("async () => { try { const r = await fetch('/api/v4/user'); const u = await r.json(); return u.username||''; } catch(e){ return ''; } }")
        log("trial auth check:", who or "ANON")
        if who != USER:
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
            pg.goto("https://gitlab.com/-/trials/new", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(4000)
            G.pass_cf(pg, 5)
            who2 = pg.evaluate("async () => { try { const r = await fetch('/api/v4/user'); const u = await r.json(); return u.username||''; } catch(e){ return ''; } }")
            log("trial auth after login:", who2 or "ANON")
        log("trial page:", pg.url[:90])
        gname = "nv" + rnd(4) + str(random.randint(100, 999))
        # fill text inputs by name/label
        filled = {}
        for inp in pg.query_selector_all('input[type="text"], input:not([type])'):
            try:
                if not inp.is_visible():
                    continue
                nm = inp.get_attribute("name") or ""
                ph = inp.get_attribute("placeholder") or ""
                key = (nm + " " + ph).lower()
                if "group" in key and "group" not in filled:
                    inp.click(); inp.fill(gname); filled["group"] = gname
                elif "company" in key and "company" not in filled:
                    inp.click(); inp.fill("Nova" + str(random.randint(100, 999)) + " GmbH"); filled["company"] = "set"
                elif "telephone" in key or "phone" in key:
                    inp.click(); inp.fill("+49 30 5557" + str(random.randint(100, 999))); filled["phone"] = "set"
            except Exception:
                pass
        log("filled:", filled)
        if "group" not in filled:
            # generic: first empty visible text input = group
            for inp in pg.query_selector_all('input[type="text"], input:not([type])'):
                try:
                    if inp.is_visible() and not (inp.input_value() or "").strip():
                        inp.click(); inp.fill(gname); filled["group"] = gname
                        log("group via first-empty:", gname)
                        break
                except Exception:
                    pass
        ok = pick_country(pg, "Germany")
        log("country picked:", ok)
        pg.screenshot(path=STAGE + "/ta_form.png")
        # submit
        resp_log.clear()
        sub = pg.evaluate("""() => {
            const b = [...document.querySelectorAll('button, input[type=submit]')].find(x => /Activate my trial/i.test(x.innerText||x.value||''));
            if (b) { b.click(); return true; }
            return false;
        }""")
        log("activate clicked:", sub)
        pg.wait_for_timeout(12000)
        G.pass_cf(pg, 6)
        rec["after_submit"] = pg.url[:140]
        log("AFTER SUBMIT:", pg.url)
        body = pg.inner_text("body")[:500].replace("\n", " | ")
        rec["body"] = body
        log("BODY:", body[:350])
        pg.screenshot(path=STAGE + "/ta_after.png")
        rec["net"] = resp_log[-12:]
        log("NET:", json.dumps(resp_log[-8:], indent=0)[:500])
        # arkose modal?
        chal = pg.evaluate("""() => {
            const ifr=[...document.querySelectorAll('iframe')].some(f=>(f.src||'').includes('arkoselabs'));
            return ifr || !!window.arkoseEnforcement || !!document.querySelector('#FunCaptcha, [class*=funcaptcha]');
        }""")
        rec["arkose_challenge"] = chal
        log("arkose challenge appeared:", chal)
        activated = "trial" not in pg.url.lower() or "congratulations" in body.lower() or "welcome" in body.lower()
        # definitive check: does /-/duo_chat work now?
        pg.goto("https://gitlab.com/-/duo_chat", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(8000)
        G.pass_cf(pg, 4)
        rec["duo_url"] = pg.url[:140]
        rec["duo_body"] = pg.inner_text("body")[:400].replace("\n", " | ")
        log("duo_chat:", pg.url[:80])
        log("duo body:", rec["duo_body"][:260])
        pg.screenshot(path=STAGE + "/ta_duo.png")
        rec["duo_ok"] = "404" not in rec["duo_body"][:60] and "sign_in" not in pg.url
        # PAT via proper settings flow
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
            pool.append({"pat": tok, "username": un or USER, "ts": time.time(), "src": "tonline_trial"})
            json.dump(pool, open(STAGE + "/pat_pool.json", "w", encoding="utf-8"), indent=1)
            log(f"PAT -> pool ({len(pool)})")
        else:
            log("PAT None (create_pat flow needs fix)")
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
log("RESULT:", json.dumps({k: v for k, v in rec.items() if k not in ('gitlab_session', 'pat', 'body', 'net')}, ensure_ascii=False)[:400])
log("TRIAL ACTIVATE DONE")
