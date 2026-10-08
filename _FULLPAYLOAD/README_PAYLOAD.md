# _FULLPAYLOAD — боевые данные (не трогать посторонним)

- `_DOCS/working_mails.txt` — 17,316 t-online.de почт (email:pass)
- `cards.txt` — 6 карт (основная очередь)
- `cards_main.txt` — 50,677 карт (полный архив, no addr)
- `cards_tg_named.txt` — 2,750 карт (TG, с именами)
- `.env` — YESCAPTCHA_KEY + IMAP конфиг

Быстрый старт:
1. `cp _FULLPAYLOAD/_DOCS/working_mails.txt _DOCS/working_mails.txt`
2. `cp _FULLPAYLOAD/.env .env`
3. `export GLAR_CARDS=_FULLPAYLOAD/cards.txt`
4. `python reg_pipeline.py`
