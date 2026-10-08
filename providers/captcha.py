"""Captcha solvers. YesCaptcha primary (balance verified 2026-09-19).
Solves: reCAPTCHA v2, Arkose FunCaptcha, Turnstile. Robust polling with retries."""
import os
from pathlib import Path
import time

import httpx

API = "https://api.yescaptcha.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

_ENV_FILE = os.environ.get("GLAR_ENV_FILE", str(Path(__file__).resolve().parent.parent / ".env"))


def _load_key():
    k = os.environ.get("YESCAPTCHA_KEY", "")
    if k:
        return k
    try:
        with open(_ENV_FILE, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("YESCAPTCHA_"):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


class YesCaptcha:
    def __init__(self, key=None):
        self.key = key or _load_key()
        if not self.key:
            raise RuntimeError("no yescaptcha key")
        self.client = httpx.Client(timeout=60)

    def _post(self, method, payload, retries=6):
        payload["clientKey"] = self.key
        last_err = None
        for i in range(retries):
            try:
                r = self.client.post(API + "/" + method, json=payload)
                d = r.json()
            except Exception as e:
                last_err = e
                time.sleep(3 + i * 2)
                continue
            ec = str(d.get("errorCode", ""))
            if d.get("errorId"):
                # transient proxy errors during polling: keep trying
                if method == "getTaskResult" and ("PROXY" in ec or "TIMEOUT" in ec):
                    last_err = RuntimeError(f"{method}: {ec}")
                    time.sleep(4 + i * 2)
                    continue
                raise RuntimeError(f"yescaptcha {method}: {ec} {d.get('errorDescription')}")
            return d
        raise RuntimeError(f"yescaptcha {method}: exhausted retries: {last_err}")

    def balance(self):
        return self._post("getBalance", {})["balance"]

    def _solve(self, task, timeout=240, poll=6):
        task_id = self._post("createTask", {"task": task})["taskId"]
        print(f"[yescaptcha] task {task_id} created")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                d = self._post("getTaskResult", {"taskId": task_id}, retries=8)
            except RuntimeError as e:
                print("[yescaptcha] poll retry:", e)
                time.sleep(poll)
                continue
            if d["status"] == "ready":
                return d["solution"]
            time.sleep(poll)
        raise TimeoutError(f"captcha task {task_id} not solved in {timeout}s")

    # ---- reCAPTCHA v2 ----
    def recaptcha_v2(self, sitekey, pageurl, proxy=None):
        task = {"type": "RecaptchaV2TaskProxyless", "websiteURL": pageurl, "websiteKey": sitekey}
        if proxy:
            task = {"type": "RecaptchaV2Task", "websiteURL": pageurl, "websiteKey": sitekey,
                    "proxyType": "http", "proxyAddress": proxy["host"], "proxyPort": proxy["port"],
                    "proxyLogin": proxy.get("user", ""), "proxyPassword": proxy.get("pass", ""),
                    "userAgent": UA}
        return self._solve(task)["gRecaptchaResponse"]

    # ---- Arkose FunCaptcha (gitlab signup + phone verify) ----
    def funcaptcha(self, public_key, surl="https://gitlab-api.arkoselabs.com", pageurl=None, data=None, proxy_url=None):
        task = {"type": "FunCaptchaTaskProxyless", "websiteURL": pageurl or surl,
                "websitePublicKey": public_key, "funcaptchaApiJSSubdomain": surl,
                "userAgent": UA}
        if data:
            task["data"] = data
        if proxy_url:
            hp = proxy_url.split("//", 1)[-1]
            host, _, port = hp.partition(":")
            task["type"] = "FunCaptchaTask"
            task.update({"proxyType": "http", "proxyAddress": host,
                         "proxyPort": int(port or 80), "proxyLogin": "", "proxyPassword": ""})
        return self._solve(task, timeout=300)["token"]

    # ---- Cloudflare Turnstile ----
    def turnstile(self, sitekey, pageurl, action=None, proxy_url=None):
        if proxy_url:
            hp = proxy_url.split("//", 1)[-1]
            creds = ""
            if "@" in hp:
                creds, hp = hp.rsplit("@", 1)
            host, _, port = hp.partition(":")
            user, _, pw = creds.partition(":")
            task = {"type": "TurnstileTask", "websiteURL": pageurl, "websiteKey": sitekey,
                    "proxyType": "http", "proxyAddress": host, "proxyPort": int(port or 80),
                    "proxyLogin": user, "proxyPassword": pw}
        else:
            task = {"type": "TurnstileTaskProxyless", "websiteURL": pageurl, "websiteKey": sitekey}
        if action:
            task["metadata"] = {"action": action}
        return self._solve(task)["token"]


class ManualCaptcha:
    def recaptcha_v2(self, sitekey, pageurl, proxy=None):
        print(f"[MANUAL CAPTCHA] recaptcha sitekey={sitekey}")
        return input("paste g-recaptcha-response: ").strip()

    def funcaptcha(self, public_key, surl=None, pageurl=None, data=None, proxy_url=None):
        print(f"[MANUAL CAPTCHA] funcaptcha pubkey={public_key}")
        return input("paste arkose token: ").strip()

    def turnstile(self, sitekey, pageurl):
        print(f"[MANUAL CAPTCHA] turnstile sitekey={sitekey}")
        return input("paste turnstile token: ").strip()


def get_solver():
    try:
        return YesCaptcha()
    except RuntimeError:
        return ManualCaptcha()
