# GUIDE — как регать авторегом и что ему надо

Полный цикл: регистрация GitLab-аккаунта -> Ultimate Trial -> Duo IDV -> пул шлюза -> OpenAI-совместимый API с computer vision и tool use (GitLab Duo управляет вашим ПК: создаёт файлы, запускает команды, смотрит на экран).

---

## 1. Что нужно авторегу (входные данные)

| Ресурс | Зачем | Формат | Кол-во на акк |
|---|---|---|---|
| **t-online.de почты** | signup + email verify (IMAP) | `email:password` в `_DOCS/working_mails.txt` | 1 |
| **Карта (US FullZ)** | Zuora card IDV (верификация для Duo) | `num|mm|yy|cvv|name|zip|...` в cards-файле | 1 (сгорает) |
| **YesCaptcha ключ** | reCAPTCHA на IDV (audio-тип, vision-solver) | env `YESCAPTCHA_KEY` | ~$0.002/акк |
| **Chrome** (не headless-режим для IDV) | signup/wizard/IDV идут в persistent profile | `chrome_reg_profile/` | 1 профиль (по очереди!) |
| **Python 3.11 + deps** | весь пайплайн | `pip install -r requirements.txt` | — |

Карта НЕ нужна для trial — только для IDV (без него Duo не даёт моделей).

## 2. Регистрация (полный пайплайн, ~13 мин)

```bash
# один акк end-to-end: signup -> email verify -> wizard -> trial
python reg_pipeline.py
# результат в C:/Users/User/tmp/glar_stage/gitlab_accounts.json:
#   username, password, email, group, gid, session, trial_ok:true
```

Стадии (можно гонять по отдельности):
1. `tonline_signup.py` — форма signup на gitlab.com, берёт почту из `working_mails.txt`, читает код по IMAP (`secureimap.t-online.de:993`).
2. `tonline_verify2.py` — подтверждение email, захват `_gitlab_session`.
3. `wizard_complete.py` — welcome wizard (Role/Who/Reason/Country), создаёт группу `XXXX-group`.
4. `trial_activate.py` — `/-/trials` -> GitLab Ultimate Trial 30 дней (без капчи).

## 3. Duo IDV (верификация — ОБЯЗАТЕЛЬНА для моделей)

Без IDV: Ultimate trial есть, но Duo Agent Platform показывает «Identity Verification required», textarea Duo-чата disabled.

```bash
python card_verify4.py <username> '<password>' <attempts> <cards_file>
# flow: login -> code gate (email OTP) -> Verify my account -> Zuora форма
#       -> reCAPTCHA audio (YesCaptcha) -> submit -> 302 /-/identity_verification/success
# сессия пишется в tn_session.json; скопируй в sess_<username>.json
```

Риски: ~25% акков банятся антифродом после успешного IDV; карта сгорает (1 на акк).
Chrome profile lock: гонять ПО ОДНОМУ акку; при `profile lock` — убить chrome.exe и удалить `SingletonLock/SingletonCookie/SingletonSocket` в `chrome_reg_profile/`.

## 4. Добавление в пул шлюза

```python
import sqlite3
con = sqlite3.connect('duo_gateway/data/duo.db')
# вставить/обновить строку accounts:
#   name=<username>-cookie, auth_type=cookie,
#   auth_value='_gitlab_session=<cookie>', enabled=1, status='active'
```
Шлюз сам проверяет модели через GraphQL `aiChatAvailableModels(namespaceId: gid группы)` — должно быть 60+ моделей.

## 5. Шлюз (OpenAI-compatible, :8088)

```bash
cd duo_gateway
python restart_gateway.py        # старт/рестарт (pid в gw.pid)
curl http://127.0.0.1:8088/health
```

Эндпоинты:
- `POST /v1/chat/completions` — чат (stream и non-stream), модели из каталога Duo
- `GET /v1/models` — каталог (69 моделей у verified-акка)
- `GET /web/` — **дашборд WebUI** (Claude-style): чат, пул акков, статистика
- `GET /v1/accounts/pool` — пул (нужен header `X-WebUI-Token`)
- `POST /v1/users/register` + JWT — пользовательские ключи

### Computer Vision
Duo UI текстовый, поэтому картинки обрабатывает локальная vision-модель (`vision_bridge.py`):
```json
{"model":"claude-opus-4.8","messages":[{"role":"user","content":[
  {"type":"text","text":"что на картинке?"},
  {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}]}]}
```
Принимает data URI / http URL / локальный путь. Env: `GATEWAY_VISION_URL` (OpenAI-compat прокси), `GATEWAY_VISION_MODEL`, `GATEWAY_VISION_TIMEOUT`.

### Tool Use — GitLab Duo управляет ПК
Включено: `server.tools: true` в config.yaml или env `GATEWAY_SERVER_TOOLS=1`.
Модель получает компактный список тулов в промпте и отвечает строкой `TOOL_CALL: {"name":...,"arguments":...}`; шлюз исполняет НА ХОСТЕ и подкармливает результат, loop до 3 раундов.

| Tool | Действие |
|---|---|
| `write` / `write_file` | **создать/перезаписать файл на ПК** (mkdir -p родителей, cap 200KB) |
| `read` / `read_file` | прочитать файл / список директории |
| `bash` / `run_command` | выполнить команду (Windows cmd/powershell), timeout 60s |
| `list` / `list_dir` | листинг директории |
| `python` | выполнить python-код |
| `calc` | безопасный арифметический eval (ast) |
| `screenshot` | **скрин экрана ПК -> vision-описание** (глаза для модели) |

Пример — Duo создаёт файл и запускает его одним запросом:
> «Use the write tool to create C:/tmp/hello.py with content print('HI'). Then use the bash tool to run it.»

Модель: `TOOL_CALL write` -> шлюз пишет файл -> `TOOL_CALL bash python C:/tmp/hello.py` -> `exit=0 HI` -> финальный ответ.

Безопасность: единственный гейт — API-ключ шлюза; держать bind на 127.0.0.1.

## 6. Дашборд

`http://127.0.0.1:8088/web/` — WebUI (файл `duo_gateway/web/index.html`):
- чат с любой моделью пула
- управление пулом акков (статус/включение)
- статистика запросов, логи ошибок
- токен: `webui_token` в config.yaml (header `X-WebUI-Token`)

## 7. Известные грабли

- **fill timeout / textarea disabled на дашборде**: у части акков Duo-панель на `/dashboard/home` гидрируется с disabled input. Фолбэк в `chat_driver.py`: переход на страницу owned-группы (`/-/group_members`) — там панель всегда активна.
- **model-switch mutation 403**: смена модели через GraphQL требует admin PAT той же группы; без PAT работает дефолтная модель акка.
- **Chrome profile lock**: два card_verify4/reg одновременно = SingletonLock. Только последовательно.
- **Бан после IDV**: антифрод Zuora банит ~25% акков после успешной верификации — закладывать в экономику.
- **Сессия живёт в cookie**: `_gitlab_session` из `gitlab_accounts.json` / `sess_*.json`; при 401 — перелогин через `login_code.py` (email OTP).

## 8. Быстрый старт (TL;DR)

```bash
pip install -r requirements.txt
# 1) почты: _DOCS/working_mails.txt (t-online email:pass)
# 2) карты: cards.txt (num|mm|yy|cvv|name|zip)
# 3) YesCaptcha: export YESCAPTCHA_KEY=***
python reg_pipeline.py                       # -> акк + trial
python card_verify4.py USER PASS 3 cards.txt # -> IDV
# 4) добавить cookie в duo_gateway/data/duo.db (accounts)
cd duo_gateway && python restart_gateway.py  # -> :8088
curl http://127.0.0.1:8088/v1/models         # 69 моделей
# дашборд: http://127.0.0.1:8088/web/
```
## Paths & configuration (portable)

All paths are relative to the repo now. Override via env vars:

| Env var | Default | Purpose |
|---|---|---|
| `GLAR_STAGE` | `./stage` | working dir: sessions, state JSON, logs, chrome profiles |
| `GLAR_MAILPOOL` | `./_DOCS/working_mails.txt` | t-online mailboxes `email:pass` per line (see `working_mails.example.txt`) |
| `GLAR_CARDS` | `$GLAR_STAGE/cards.txt` | card queue for `card_verify4.py` |
| `GLAR_ENV_FILE` | `./.env` | captcha keys for `providers/captcha.py` |
| `GLAR_DEFAULT_PWD` | — | default account password for helper scripts |
| `YESCAPTCHA_API_KEY` | — | captcha solver key |
| `GATEWAY_VISION_URL` / `GATEWAY_VISION_MODEL` | `http://127.0.0.1:16432/v1/chat/completions` / `qwen3-vl-plus` | vision sidecar |

Quick start:

```bash
git clone https://github.com/GroundPhasePraise/gitlab-duo-farm
cd gitlab-duo-farm
pip install -r requirements.txt
playwright install chromium          # or: patchright install chromium
cp _DOCS/working_mails.example.txt _DOCS/working_mails.txt   # fill mailboxes
export YESCAPTCHA_API_KEY=...        # or put in .env
python reg_pipeline.py               # full signup -> verify -> wizard -> trial
python card_verify4.py <user> <pwd> <attempts> <cards_file>
cd duo_gateway && python server.py   # gateway on :8088, dashboard at /web
```
