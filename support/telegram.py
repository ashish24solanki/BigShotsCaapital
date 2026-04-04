import requests
from config.bot_config import (
    BOT_TOKEN,
    TRIAL_CHAT_ID,
    PRO_CHAT_ID
)

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def _send(chat_id: str, text: str):
    try:
        requests.post(
            API_URL,
            data={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
    except Exception:
        pass


def send_message(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": PRO_CHAT_ID,
        "text": text
    }
    requests.post(url, data=payload, timeout=10)


def send_trial(message: str):
    _send(TRIAL_CHAT_ID, message)


def send_pro(message: str):
    _send(PRO_CHAT_ID, message)
