# gitlab-duo-farm

> Полный гайд (что нужно авторегу, как регать, IDV, пул, шлюз, дашборд): **[GUIDE.md](GUIDE.md)**

Automated GitLab account registration + Duo Agent Platform trial farming + OpenAI-compatible gateway over the account pool.

## Pipeline (proven live, ~13 min/account)

`reg_pipeline.py` orchestrates:

1. **tonline_signup.py** — signup on gitlab.com with t-online.de mailbox (IMAP code extraction). No phone required.
2. **tonline_verify2.py** — email verification, session capture.
3. **wizard_complete.py** — welcome wizard (Role/Who/Reason/Country) -> group namespace created.
4. **trial_activate.py** — `/-/trials` Ultimate + Duo Agent Platform 30-day trial, no captcha.

Result: account with active `ultimate_trial` group + Duo seat assigned (`duo_seat_pat.py`).

## Gateway (`duo_gateway/`)

OpenAI-compatible proxy over a pool of Duo accounts (FastAPI + Playwright):

- `/v1/chat/completions`, `/v1/models`, `/health`
- Account pool in SQLite (`duo.db`), round-robin + cooldown on failure
- Session injection via `_gitlab_session` cookie (no login code needed) — see `restore_profile_h4.py`
- Tool use via FUNCTION-CALLING BRIDGE (`server_tools.py`) + SSE streaming
- Duo workflow executes ONLY from browser session (PAT-created workflows stay CREATED forever)

## Key files

| File | Purpose |
|------|---------|
| `reg_pipeline.py` | full single-account pipeline |
| `providers/` | email (IMAP/gmail alias), SMS (2no.pl), captcha (YesCaptcha), proxies |
| `card_verify4.py` | Zuora card IDV flow (reCAPTCHA audio + whisper solver) |
| `restore_profile_h4.py` | session-cookie injection bypass |
| `duo_gateway/server.py` | gateway core |
| `STATUS.md` | full ops log + protocol findings |

## Notes

- reCAPTCHA Enterprise audio challenge solved locally with faster-whisper (words, not digits), round 0
- GitLab throttles login codes after 2-3/day — use session injection instead
- gmail +alias is rejected since ~21.09 ("Email is not allowed") — t-online.de works

## Computer Vision + Tool Use (2026-10-08)

- **Vision**: OpenAI-style `image_url` parts (data URI / http URL / local path) are
  described by a local vision model (`vision_bridge.py`, default qwen3-vl-plus via
  dashscope proxy :16432) and injected into the Duo prompt as `[Attached image]`.
  Verified: image with text "ZEBRA-42" -> model replied exactly "ZEBRA-42".
- **Server tools**: gateway executes whitelisted tools on the host PC
  (bash/read/write/list/calc/python/**screenshot**) and loops up to 3 rounds.
  `screenshot` = screen capture -> vision description (the model gets eyes on the PC).
  Verified: bash `hostname && whoami` -> real output returned; screenshot tool ->
  accurate description of the live desktop.
- Env: `GATEWAY_VISION_URL`, `GATEWAY_VISION_MODEL`, `GATEWAY_VISION_TIMEOUT`.
