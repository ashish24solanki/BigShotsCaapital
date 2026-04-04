import os
import sys
import requests

# add project root to path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.bot_config import PORT_BOT_TOKEN, PORT_BOT_CHAT_ID

r = requests.post(
    f"https://api.telegram.org/bot{PORT_BOT_TOKEN}/sendMessage",
    data={
        "chat_id": PORT_BOT_CHAT_ID,
        "text": "TEST MESSAGE FROM SCRIPT"
    },
    timeout=10
)

print("STATUS:", r.status_code)
print("RESPONSE:", r.text)
