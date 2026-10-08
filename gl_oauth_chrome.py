"""GitLab autoreg via GitHub OAuth v2 — real Chrome, CF interstitial clicker,
YesCaptcha turnstile-widget injection, trial + PAT + API verification.

Flow per account:
  GH login+TOTP -> gitlab sign_up (pass CF: click checkbox / solve widget)
  -> Continue with GitHub -> Authorize -> callback (pass CF; if landed on
  sign_in -> re-click GitHub OAuth = instant callback on established session)
  -> Ultimate trial (/-/trial_registrations/new) -> PAT(api,ai_features,...)
  -> GET /api/v4/user with PAT (honest liveness proof).

Memory: gh_bad.json (unverified-email etc), gitlab_accounts.json (done=ready).
Usage: python gl_oauth_chrome.py [target_valid_pats] [start_index]
"""
if __name__ != "__main__" and not __import__("os").environ.get("GLAR_ALLOW_IMPORT"):
    raise ImportError(f"{__name__}: script-only module — run it directly (python {__file__})")

import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import STAGE as _S
import time

import httpx
import pyotp
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA_PATH = str(_S / "gh_for_oauth.json")
PROFILE = str(_S / "chrome_gl_profile")
OUT = str(_S / "gitlab_accounts.json")
BAD = str(_S / "gh_bad.json")
TRIAL_URL = "https://gitlab.com/-/trial_registrations/new"


def log(*a):
    print(*a, flush=True)


# ---------------- captcha (lazy, never manual/blocking) ----------------

_SOLVER = None


def solver():
    global _SOLVER
    if _SOLVER is None:
        from providers.captcha import YesCaptcha
        s = YesCaptcha()
        _SOLVER = s if s.key else False
    return _SOLVER or None


# ---------------- bad/done account memory ----------------

def load_bad():
    try:
        return set(json.load(open(BAD, encoding="utf-8")))
    except Exception:
        return set()


def save_bad(bad):
    json.dump(sorted(bad), open(BAD, "w", encoding="utf-8"), indent=1)


# ---------------- cloudflare ----------------

def cf_frame_click(pg):
    """Click the 'Verify you are human' checkbox inside the CF challenge iframe."""
    for fr in pg.frames:
        if "challenges.cloudflare.com" not in (fr.url or ""):
            continue
        for sel in ('input[type="checkbox"]', 'label.cb-lb', '[role="checkbox"]',
                    '#challenge-stage input'):
            try:
                fr.click(sel, timeout=2500, force=True)
                return True
            except Exception:
                pass
    return False


def pass_cf(pg, tries=10):
    """Wait out / click through a CF interstitial. True when page is past it."""
    for i in range(tries):
        try:
            body = pg.inner_text("body")[:300].lower()
        except Exception:
            body = ""
        if "security verification" not in body and "verify you are human" not in body:
            return True
        if cf_frame_click(pg):
            log(f"  cf: checkbox clicked (try {i + 1})")
        pg.wait_for_timeout(4500)
    return False


def inject_turnstile_widget(pg):
    """If the page embeds a cf-turnstile FORM widget, solve via YesCaptcha and inject."""
    try:
        el = pg.query_selector('.cf-turnstile[data-sitekey], [data-sitekey][class*="turnstile"]')
        if not el:
            return False
        sitekey = el.get_attribute("data-sitekey")
        if not sitekey:
            return False
        inp = pg.query_selector('input[name="cf-turnstile-response"]')
        if inp and (inp.input_value() or "").strip():
            return True  # already solved
        s = solver()
        if s is None:
            log("  turnstile widget present but no YesCaptcha key — cannot solve")
            return False
        log(f"  solving turnstile widget sitekey={sitekey[:16]}...")
        tok = s.turnstile(sitekey, pg.url)
        pg.evaluate("(t) => { document.querySelectorAll('[name=\"cf-turnstile-response\"]')"
                    ".forEach(e => e.value = t); }", tok)
        log("  turnstile token injected")
        return True
    except Exception as e:
        log("  turnstile inject err:", str(e)[:90])
        return False


# ---------------- github ----------------

def _fill_login(pg, acc):
    pg.fill('input[name="login"]', acc["email"])
    pg.fill('input[name="password"]', acc["password"])
    pg.click('input[type="submit"], button[type="submit"]')
    pg.wait_for_timeout(4000)


def _gh_session_user(pg):
    try:
        return (pg.evaluate("() => { const m=document.querySelector('meta[name=\"user-login\"]');"
                            " return m ? m.content : ''; }") or "").strip()
    except Exception:
        return ""


def gh_login(pg, acc):
    pg.goto("https://github.com/login", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(1500)
    if pg.query_selector('input[name="login"]'):
        _fill_login(pg, acc)
    else:
        cur = _gh_session_user(pg)
        if cur and cur.lower() != acc["login"].lower():
            log(f"  gh: session is '{cur}', switching to '{acc['login']}'")
            pg.goto("https://github.com/logout", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(1500)
            try:
                pg.click('button[type="submit"], input[type="submit"]', timeout=5000)
            except Exception:
                pass
            pg.wait_for_timeout(3000)
            pg.goto("https://github.com/login", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(1500)
            if pg.query_selector('input[name="login"]'):
                _fill_login(pg, acc)
    if "two-factor" in pg.url or pg.query_selector('input[name="app_otp"]'):
        pg.fill('input[name="app_otp"]', pyotp.TOTP(acc["totp"]).now())
        try:
            pg.click('button[type="submit"]', timeout=6000)
        except Exception:
            pass
        pg.wait_for_timeout(5000)
    cur = _gh_session_user(pg)
    ok = ("github.com/login" not in pg.url) and ("two-factor" not in pg.url) and \
        (not cur or cur.lower() == acc["login"].lower())
    log("  gh_login ok:", ok, "| session:", cur or "?", "| want:", acc["login"])
    return ok


def click_github_oauth(pg):
    """Click the GitHub OAuth control — works on sign_up AND sign_in.
    Form-first (robust), then text fallbacks ('Continue with GitHub' / 'GitHub')."""
    try:
        btn = pg.query_selector(
            'form[action*="users/auth/github"] button[type="submit"],'
            ' form[action*="users/auth/github"] input[type="submit"]')
        if btn:
            btn.click(timeout=6000)
            return True
    except Exception:
        pass
    for pat in ("Continue with GitHub", "GitHub"):
        try:
            pg.get_by_text(pat).first.click(timeout=4000)
            return True
        except Exception:
            pass
    try:
        return bool(pg.evaluate("""() => {
            const a = [...document.querySelectorAll('a,button')]
                .find(e => /Continue with GitHub|^\\s*GitHub\\s*$/i.test(e.innerText || ''));
            if (a) { a.click(); return true; }
            return false;
        }"""))
    except Exception:
        return False


# ---------------- gitlab steps ----------------

def start_trial(pg):
    pg.goto(TRIAL_URL, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    pass_cf(pg, 4)
    for sel, val in [('input[name="trial_registration[first_name]"]', "Alex"),
                     ('input[name="trial_registration[last_name]"]', "Morgan"),
                     ('input[name*="company"], input[name*="organization"]', "Startup LLC")]:
        try:
            el = pg.query_selector(sel)
            if el:
                el.fill(val)
        except Exception:
            pass
    try:
        for sel in pg.query_selector_all("select"):
            try:
                sel.select_option(index=1)
            except Exception:
                pass
    except Exception:
        pass
    inject_turnstile_widget(pg)
    try:
        pg.click('input[type="submit"], button[type="submit"]', timeout=6000)
    except Exception:
        pass
    pg.wait_for_timeout(6000)
    pass_cf(pg, 4)
    url = pg.url
    ok = "trial_registrations/new" not in url
    log(f"  trial -> {url[:70]} submitted={ok}")
    return url


def create_pat(pg):
    pg.goto("https://gitlab.com/-/user_settings/personal_access_tokens",
            wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    if not pass_cf(pg):
        return None
    if "sign_in" in pg.url or "users/sign_in" in pg.url:
        log("  PAT: not logged into gitlab", pg.url[:50])
        return None
    log("  PAT page OK:", pg.url[:55])
    try:
        pg.fill('input[name="personal_access_token[name]"]', "duo-" + str(int(time.time()))[-6:])
    except Exception:
        pass
    for scope in ("api", "ai_features", "read_user", "read_api"):
        try:
            cb = pg.query_selector(f'input[value="{scope}"]')
            if cb and not cb.is_checked():
                cb.check()
        except Exception:
            pass
    try:
        pg.click('input[type="submit"], button[type="submit"]')
        pg.wait_for_timeout(4000)
    except Exception:
        pass
    for sel in ('#created-personal-access-token', 'input[id*="token"][value]'):
        el = pg.query_selector(sel)
        if el:
            try:
                v = (el.input_value() or "").strip()
                if v.startswith("glpat-"):
                    return v
            except Exception:
                pass
    return None


def verify_pat(pat):
    """Honest liveness proof: GET /api/v4/user with the token."""
    try:
        r = httpx.get("https://gitlab.com/api/v4/user",
                      headers={"PRIVATE-TOKEN": pat}, timeout=25)
        if r.status_code == 200:
            return r.json().get("username")
    except Exception as e:
        log("  verify_pat err:", str(e)[:70])
    return None


# ---------------- main flow per account ----------------

def run_one(ctx, acc, idx):
    pg = ctx.new_page()
    pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    rec = {"gh_login": acc["login"], "gh_email": acc.get("email"), "ts": time.time()}
    try:
        # 1. GitHub session first
        if not gh_login(pg, acc):
            rec["error"] = "gh login failed"
            return rec
        if "unverified" in pg.url:
            rec["error"] = "gh_unverified"
            return rec
        # 2. gitlab signup
        pg.goto("https://gitlab.com/users/sign_up", wait_until="domcontentloaded", timeout=75000)
        pg.wait_for_timeout(4000)
        if not pass_cf(pg):
            rec["error"] = "CF stuck signup"
            return rec
        inject_turnstile_widget(pg)
        log(f"[{idx}] signup reached, arkose={'arkose' in pg.content().lower()}")
        # 3. Continue with GitHub
        clicked = click_github_oauth(pg)
        log(f"[{idx}] github-click={clicked}")
        pg.wait_for_timeout(6000)
        log(f"[{idx}] -> {pg.url[:70]}")
        # 4. Authorize on GitHub
        if "oauth/authorize" in pg.url:
            try:
                pg.wait_for_selector('button[name="authorize"][value="1"]', timeout=12000)
                pg.click('button[name="authorize"][value="1"]', timeout=6000)
                log(f"[{idx}] authorize clicked (value=1)")
            except Exception as e:
                log(f"[{idx}] authorize fail {str(e)[:50]} — js value=1 click")
                pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.name==='authorize'&&x.value==='1'); if(b)b.click(); }""")
            pg.wait_for_timeout(9000)
        pass_cf(pg, 10)
        log(f"[{idx}] landed: {pg.url[:75]}")
        # 5. fallback: bounced to sign_in -> click GitHub OAuth again (session already
        #    established on both sides => callback is instant, often CF passes 2nd time)
        if "users/sign_in" in pg.url:
            log(f"[{idx}] sign_in fallback: re-click GitHub OAuth")
            inject_turnstile_widget(pg)
            if click_github_oauth(pg):
                pg.wait_for_timeout(9000)
                if "oauth/authorize" in pg.url:
                    try:
                        pg.click('button[name="authorize"][value="1"]', timeout=6000)
                        log(f"[{idx}] fallback authorize clicked (value=1)")
                    except Exception:
                        pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.name==='authorize'&&x.value==='1'); if(b)b.click(); }""")
                    pg.wait_for_timeout(9000)
                pass_cf(pg, 10)
                log(f"[{idx}] fallback landed: {pg.url[:75]}")
        rec["landed"] = pg.url[:110]
        # 5.5 identity_verification gate: Arkose FunCaptcha + phone SMS via 2nd-no.com
        if "identity_verification" in pg.url:
            try:
                from gl_idver import handle_identity_verification
                if handle_identity_verification(pg):
                    log(f"[{idx}] identity_verification PASSED -> {pg.url[:60]}")
                else:
                    rec["error"] = "idver failed"
                    rec["status"] = "idver_failed"
                    log(f"[{idx}] identity_verification FAILED at {pg.url[:60]}")
                    rec["landed"] = pg.url[:110]
                    return rec
            except Exception as e:
                rec["error"] = f"idver exc: {str(e)[:80]}"
                rec["status"] = "idver_failed"
                return rec
        # 6. success detection + trial + PAT + verify
        on_gl = pg.url.startswith("https://gitlab.com") and \
            "users/sign_in" not in pg.url and "users/sign_up" not in pg.url
        if on_gl:
            rec["trial_url"] = start_trial(pg)
            pg.screenshot(path=str(_S / f"trial_{idx}.png"))
            pg.goto("https://gitlab.com/-/profile", wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(3000)
            pass_cf(pg, 5)
            try:
                rec["gl_username"] = pg.evaluate(
                    "() => { const e=document.querySelector('#username, .username, [data-testid=profile-username]');"
                    " return e ? (e.value||e.innerText).trim() : null; }")
            except Exception:
                pass
            tok = create_pat(pg)
            if tok:
                rec["pat"] = tok
                uname = verify_pat(tok)
                rec["pat_valid"] = bool(uname)
                if uname:
                    rec["gl_username"] = uname
                rec["status"] = "ready" if uname else "pat_unverified"
                log(f"[{idx}] PAT {tok[:14]}... valid={rec['pat_valid']}")
            else:
                rec["status"] = "no_pat"
        else:
            rec["error"] = "no land " + pg.url[:50]
            rec["status"] = "failed"
        pg.screenshot(path=str(_S / f"glc_{idx}.png"))
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {str(e)[:100]}"
        log(f"[{idx}] ERR {rec['error']}")
    finally:
        try:
            pg.close()
        except Exception:
            pass
    return rec


if __name__ == "__main__":
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    accs = json.load(open(UA_PATH, encoding="utf-8"))
    bad = load_bad()
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        old = []
    done = {r["gh_login"] for r in old if r.get("status") == "ready"}
    log(f"pool={len(accs)} bad={sorted(bad)} done={sorted(done)} target_valid_pats={target}")
    results = []
    made = 0
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            PROFILE, headless=False, channel="chrome",
            viewport={"width": 1366, "height": 900}, locale="en-US",
            args=["--disable-blink-features=AutomationControlled", "--no-first-run",
                  "--no-default-browser-check"],
        )
        i = start
        tried = 0
        while made < target and tried < len(accs):
            acc = accs[i % len(accs)]
            i += 1
            tried += 1
            if acc["login"] in bad or acc["login"] in done:
                log(f"[skip] {acc['login']} (bad/done)")
                continue
            r = run_one(ctx, acc, i % len(accs))
            results.append(r)
            log(f"[{r['gh_login']}] RESULT status={r.get('status')} "
                f"pat={'YES' if r.get('pat') else 'no'} valid={r.get('pat_valid')} err={r.get('error')}")
            if r.get("error") == "gh_unverified":
                bad.add(acc["login"])
                save_bad(bad)
            if r.get("pat_valid"):
                made += 1
        ctx.close()
    old.extend(results)
    json.dump(old, open(OUT, "w"), indent=1)
    valid = sum(1 for r in results if r.get("pat_valid"))
    log(f"SAVED -> {OUT} | valid PATs this run: {valid}/{len(results)}")
