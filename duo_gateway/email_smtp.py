#!/usr/bin/env python3
"""Email verification via SMTP (config-driven)"""
import logging, os, random, smtplib, time
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

logger = logging.getLogger("email")

_codes: Dict[str, dict] = {}

SMTP_HOST = "smtp.163.com"
SMTP_PORT = 465
SMTP_USER = ""
SMTP_PASS = ""
SMTP_SENDER = ""
SMTP_TIMEOUT = 15


def load_smtp_config(config_path: Path = None):
    """从 config.yaml 加载 SMTP 配置，环境变量优先级最高。"""
    global SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_SENDER, SMTP_TIMEOUT

    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"

    defaults = {
        "host": "smtp.163.com",
        "port": 465,
        "user": "",
        "password": "",
        "sender": "",
        "timeout": 15,
    }
    cfg = defaults.copy()

    if yaml and config_path.exists():
        try:
            user_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            smtp_cfg = user_cfg.get("smtp", {})
            for k in defaults:
                if k in smtp_cfg and smtp_cfg[k] is not None:
                    cfg[k] = smtp_cfg[k]
        except Exception as e:
            logger.warning("Failed to load config.yaml for SMTP: %s", e)

    env_map = {
        "host": "SMTP_HOST",
        "port": "SMTP_PORT",
        "user": "SMTP_USER",
        "password": "SMTP_PASS",
        "sender": "SMTP_SENDER",
        "timeout": "SMTP_TIMEOUT",
    }
    for k, env_var in env_map.items():
        val = os.environ.get(env_var)
        if val is not None:
            cfg[k] = int(val) if k == "port" or k == "timeout" else val

    SMTP_HOST = cfg["host"]
    SMTP_PORT = cfg["port"]
    SMTP_USER = cfg["user"]
    SMTP_PASS = cfg["password"]
    SMTP_SENDER = cfg["sender"] or cfg["user"]
    SMTP_TIMEOUT = cfg["timeout"]


def send_code(email: str) -> str:
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SMTP not configured. Set smtp.user / smtp.password in config.yaml or env vars.")
    code = str(random.randint(100000, 999999))
    msg = MIMEText(f"您的 GitLab Duo Proxy 验证码是：{code}\n\n5 分钟内有效。", "plain", "utf-8")
    msg["Subject"] = "GitLab Duo Proxy 邮箱验证"
    msg["From"] = SMTP_SENDER
    msg["To"] = email
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_SENDER, [email], msg.as_string())
        _codes[email] = {"code": code, "expires": time.time() + 300}
        logger.info("Verification code sent to %s", email)
        return "ok"
    except Exception as e:
        logger.error("SMTP error: %s", e)
        raise

def verify_code(email: str, code: str) -> bool:
    entry = _codes.get(email)
    if not entry:
        return False
    if time.time() > entry["expires"]:
        del _codes[email]
        return False
    if entry["code"] != code:
        return False
    del _codes[email]
    return True
