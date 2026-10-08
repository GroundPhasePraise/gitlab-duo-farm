"""paths.py — portable path config. Override via env vars:
  GLAR_STAGE     working dir for state/sessions/logs (default: ./stage next to repo)
  GLAR_MAILPOOL  t-online mailbox list file, email:pass per line (default: ./_DOCS/working_mails.txt)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGE = Path(os.environ.get("GLAR_STAGE", str(ROOT / "stage")))
STAGE.mkdir(parents=True, exist_ok=True)
MAIL_POOL = Path(os.environ.get("GLAR_MAILPOOL", str(ROOT / "_DOCS" / "working_mails.txt")))
PY = sys.executable
