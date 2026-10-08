"""SMS providers: sms-activate API + manual (operator via API /solve endpoint)."""
import time

import httpx


class SmsActivate:
    BASE = "https://api.sms-activate.org/stubs/handler_api.php"

    def __init__(self, api_key, country=186):  # 186 = USA cheap; adjust per need
        self.key = api_key
        self.country = country
        self.client = httpx.Client(timeout=30)

    def _call(self, **params):
        params["api_key"] = self.key
        r = self.client.get(self.BASE, params=params)
        return r.text

    def balance(self):
        t = self._call(action="getBalance")
        return t.split(":")[-1] if ":" in t else t

    def get_number(self, service="ot"):
        t = self._call(action="getNumber", service=service, country=self.country)
        # ACCESS_NUMBER:<activation_id>:<phone>
        if t.startswith("ACCESS_NUMBER"):
            _, act_id, phone = t.split(":")
            return act_id, "+" + phone
        raise RuntimeError(f"sms-activate getNumber failed: {t}")

    def status(self, act_id):
        t = self._call(action="getStatus", id=act_id)
        # STATUS_OK:<code> or STATUS_WAIT_CODE
        if t.startswith("STATUS_OK"):
            return t.split(":", 1)[1]
        return None

    def wait_code(self, act_id, timeout=300, poll=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            code = self.status(act_id)
            if code:
                return code
            time.sleep(poll)
        return None

    def finish(self, act_id, status=6):  # 6=complete, 8=cancel
        return self._call(action="setStatus", id=act_id, status=status)


class ManualSms:
    """Operator mode: pipeline waits for POST /solve with the OTP code.
    Use with 2nd/snd-like services or free web numbers where you read the SMS yourself."""

    def __init__(self, wait_fn):
        # wait_fn(kind, request, timeout) -> answer  (db.wait_otp wired in)
        self.wait_fn = wait_fn

    def request_code(self, account_id, phone_hint="", timeout=600):
        return self.wait_fn(account_id, "sms", phone_hint, timeout)
