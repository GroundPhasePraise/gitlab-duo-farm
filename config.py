"""Config - gitlab-autoreg."""
import os

_e = os.environ.get

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "accounts.db")
API_HOST = _e("GLAR_HOST", "127.0.0.1")
API_PORT = int(_e("GLAR_PORT", "8100"))

CAPTCHA_PROVIDER = _e("GLAR_CAPTCHA", "manual")  # manual | yescaptcha | twocaptcha
YESCAPTCHA_KEY = _e("GLAR_YESCAPTCHA", "")
TWOCAPTCHA_KEY = _e("TWOCAPTCHA_KEY", "")

EMAIL_PROVIDER = _e("GLAR_EMAIL", "gmail")  # gmail | tempmail | imap
IMAP_FILE = _e("GLAR_IMAP_FILE", r"C:\Users\User\Desktop\avtoreg\working_mails.txt")

SMS_PROVIDER = _e("GLAR_SMS", "manual")  # manual | smsactivate | tempnumber
SMSACTIVATE_KEY = _e("SMSACTIVATE_KEY", "")

HEADLESS = _e("GLAR_HEADLESS", "1") == "1"
PROXY = _e("GLAR_PROXY", "")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

GITLAB = "https://gitlab.com"
TRIAL_URL = GITLAB + "/-/trial_registrations/new"
SIGNUP_URL = GITLAB + "/users/sign_up"
