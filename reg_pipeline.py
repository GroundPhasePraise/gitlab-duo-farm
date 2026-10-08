"""reg_pipeline.py — orchestrates the full single-account pipeline via subprocesses:
  1. tonline_signup.py     (Firefox/Juggler, t-online email, Triolan IP)  -> account created + IDV email step
  2. tonline_verify2.py    (aged chrome, fresh IMAP code)                 -> email verified, NO phone
  3. wizard_complete.py    (welcome wizard dropdowns)                     -> group namespace
  4. trial_activate.py     (/-/trials/new, no captcha)                    -> Ultimate + Duo Agent Platform 30d
Result: account ready for card_verify4.py (Duo IDV via Zuora card).
Usage: reg_pipeline.py"""
if __name__ != "__main__" and not __import__("os").environ.get("GLAR_ALLOW_IMPORT"):
    raise ImportError(f"{__name__}: script-only module — run it directly (python {__file__})")

import json
import subprocess
from pathlib import Path
import sys
import time

from paths import PY, STAGE as _STAGE  # portable
PY = str(PY)
DIR = str(Path(__file__).resolve().parent)
STAGE = str(_STAGE)
OUT = STAGE + "/gitlab_accounts.json"


def log(*a):
    print(*a, flush=True)


def run_stage(script, args=(), timeout=560):
    cmd = [PY, script] + list(args)
    log(f"=== RUN {script} {' '.join(str(a) for a in args)} ===")
    try:
        r = subprocess.run(cmd, cwd=DIR, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="ignore")
        tail = "\n".join([l for l in (r.stdout or "").splitlines() if l.strip()][-12:])
        log(tail)
        if r.returncode != 0:
            log("STDERR:", (r.stderr or "")[-300:])
        return r.returncode, r.stdout or ""
    except subprocess.TimeoutExpired:
        log(f"{script} TIMEOUT")
        return -1, ""


def rec_since(rtype, ts_min):
    """Last record of rtype NEWER than ts_min — never picks stale records from previous runs
    (bug: farm2 ran stages under an old account because a timed-out signup never wrote its record)."""
    try:
        recs = json.load(open(OUT, encoding="utf-8"))
        for r in reversed(recs):
            if r.get("type") == rtype and (r.get("ts") or 0) >= ts_min:
                return r
    except Exception:
        pass
    return None


def main():
    t0 = time.time()
    # stage 1: signup
    rc, out = run_stage("tonline_signup.py")
    rec = rec_since("tonline_signup", t0)
    if not rec or not rec.get("username"):
        log("FATAL: no signup record"); return 1
    user, pwd, email = rec["username"], rec["password"], rec["email"]
    log(f"ACCOUNT: {user} / {pwd} / {email} | idv={rec.get('idv')} landed={str(rec.get('landed'))[:60]}")
    if not rec.get("idv", True):
        log("NOTE: signup did not land on IDV (unexpected) — continuing anyway")
    # stage 2: email verify (needs the code mail; tonline_verify2 resends + reads fresh)
    rc, out = run_stage("tonline_verify2.py", (user, pwd, email), timeout=600)
    rec2 = rec_since("tonline_verify2", t0)
    if not rec2 or not rec2.get("verified"):
        log("FATAL: email verify failed:", json.dumps(rec2 or {}, ensure_ascii=False)[:200])
        return 2
    log("EMAIL VERIFIED (no phone)")
    # stage 3: wizard
    rc, out = run_stage("wizard_complete.py", (user, pwd), timeout=600)
    rec3 = rec_since("wizard_complete", t0)
    log("wizard after:", str((rec3 or {}).get("after_wizard"))[:80])
    # stage 4: trial
    rc, out = run_stage("trial_activate.py", (user, pwd), timeout=600)
    rec4 = rec_since("trial_activate", t0)
    trial_ok = bool(rec4 and "nv" in str(rec4.get("after_submit", "")) and rec4.get("arkose_challenge") is False)
    log("TRIAL:", json.dumps({k: str(v)[:80] for k, v in (rec4 or {}).items() if k in ("after_submit", "arkose_challenge", "duo_url")}, ensure_ascii=False))
    result = {"ts": time.time(), "type": "pipeline_account", "username": user, "password": pwd,
              "email": email, "email_verified": True,
              "trial_group": str((rec4 or {}).get("after_submit", "")).split("gitlab.com/")[-1][:30],
              "trial_ok": trial_ok, "dur_s": int(time.time() - t0)}
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        old = []
    old.append(result)
    json.dump(old, open(OUT, "w", encoding="utf-8"), indent=1)
    log("PIPELINE RESULT:", json.dumps(result, ensure_ascii=False))
    return 0 if trial_ok else 3


if __name__ == "__main__":
    sys.exit(main())
