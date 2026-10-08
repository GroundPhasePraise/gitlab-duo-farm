"""duo_seat_pat.py — assign a Duo seat to the user in the trial group, verify /-/duo_chat,
then create a PAT via DOM-aware flow. Saves everything for the gateway."""
if __name__ != "__main__" and not __import__("os").environ.get("GLAR_ALLOW_IMPORT"):
    raise ImportError(f"{__name__}: script-only module — run it directly (python {__file__})")

import json
import re
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
GROUP = sys.argv[3] if len(sys.argv) > 3 else "nvvdkt666"


def log(*a):
    print(*a, flush=True)


with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        viewport={"width": 1440, "height": 950}, locale="en-US",
        args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"])
    pg = ctx.new_page()
    pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    rec = {"ts": time.time(), "type": "duo_seat_pat", "username": USER, "group": GROUP}
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
        log("login:", pg.url[:80])
        # 1) discover seat management: scan group settings nav for duo/seat/subscription links
        for url in [f"https://gitlab.com/groups/{GROUP}/-/settings/general",
                    f"https://gitlab.com/groups/{GROUP}/-/settings/usage_quotas",
                    f"https://gitlab.com/groups/{GROUP}/-/settings"]:
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(5000)
            G.pass_cf(pg, 4)
            links = pg.evaluate("""() => {
                const out = [];
                document.querySelectorAll('a').forEach(a => {
                    const t = (a.innerText||'').trim().toLowerCase();
                    const h = a.href||'';
                    if (/duo|seat|subscription|trial|ai/i.test(t) || /duo|seat|subscription/i.test(h)) out.push({t:(a.innerText||'').trim().slice(0,50), h:h.slice(0,110)});
                });
                return out.slice(0,25);
            }""")
            log(f"settings links on {pg.url[:70]}:")
            for l in links:
                log("   ", l["t"], "->", l["h"])
            if links:
                rec[f"links_{url.split('/')[-1] or 'root'}"] = links
                break
        pg.screenshot(path=STAGE + "/ds_settings.png")
        # 2) try known Duo seat URLs directly
        for url in [f"https://gitlab.com/groups/{GROUP}/-/settings/duo",
                    f"https://gitlab.com/groups/{GROUP}/-/duo",
                    f"https://gitlab.com/{GROUP}/-/settings/duo"]:
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(4500)
            if "404" not in pg.inner_text("body")[:200]:
                log("DUO SETTINGS FOUND:", pg.url[:90])
                rec["duo_settings_url"] = pg.url
                body = pg.inner_text("body")[:500].replace("\n", " | ")
                log("  body:", body[:300])
                rec["duo_settings_body"] = body
                pg.screenshot(path=STAGE + "/ds_duo.png")
                # look for seat assign buttons
                btns = pg.evaluate("""() => {
                    const out=[]; document.querySelectorAll('button,a').forEach(b=>{
                        const t=(b.innerText||'').trim();
                        if (/seat|assign|add user|manage/i.test(t) && b.offsetParent) out.push(t.slice(0,60));
                    }); return out.slice(0,12);
                }""")
                log("  seat buttons:", btns)
                rec["seat_buttons"] = btns
                break
        # 3) probe duo_chat now
        pg.goto("https://gitlab.com/-/duo_chat", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(7000)
        G.pass_cf(pg, 4)
        rec["duo_url"] = pg.url[:140]
        rec["duo_body"] = pg.inner_text("body")[:300].replace("\n", " | ")
        log("duo_chat:", pg.url[:80])
        log("duo body:", rec["duo_body"][:200])
        pg.screenshot(path=STAGE + "/ds_chat.png")
        # 4) PAT page DOM dump + creation attempt
        pg.goto("https://gitlab.com/-/user_settings/personal_access_tokens", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(5000)
        G.pass_cf(pg, 4)
        dom = pg.evaluate("""() => {
            const out = {inputs: [], buttons: [], checks: []};
            document.querySelectorAll('input, textarea').forEach(i => {
                if (!i.offsetParent && i.type !== 'checkbox' && i.type !== 'hidden') return;
                out.inputs.push({tag:i.tagName, type:i.type, name:i.name||'', id:i.id||'', ph:i.placeholder||''});
            });
            document.querySelectorAll('input[type=checkbox]').forEach(c => {
                out.checks.push({name:c.name||'', value:c.value||'', checked:c.checked});
            });
            document.querySelectorAll('button').forEach(b => {
                if (b.offsetParent) out.buttons.push((b.innerText||'').trim().slice(0,50));
            });
            return out;
        }""")
        rec["pat_dom"] = dom
        log("PAT DOM inputs:", json.dumps(dom["inputs"])[:400])
        log("PAT DOM checks:", json.dumps(dom["checks"])[:300])
        log("PAT DOM buttons:", dom["buttons"][:8])
        pg.screenshot(path=STAGE + "/ds_pat.png")
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
log("SEAT PAT DONE")
