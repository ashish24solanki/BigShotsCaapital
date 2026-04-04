import os
import sys
import webbrowser
from kiteconnect import KiteConnect
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.kite_config import API_KEY, API_SECRET

# =====================================================
# FILE PATHS
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")

kite = KiteConnect(api_key=API_KEY)

print("\n==============================")
print("🔐 Zerodha Access Token Setup")
print("==============================\n")

# Auto open login URL
login_url = kite.login_url()
print("🌐 Opening Zerodha login in browser...")
webbrowser.open(login_url)

print("\n✅ After login, copy the FULL redirect URL and paste below.")
print("Example:")
print("https://kite.trade/connect/login?api_key=XXXX&request_token=YYYY\n")

input_val = input("📌 Paste full URL or request_token here: ").strip()

# Attempt to extract request_token from URL
parsed = urlparse(input_val)
request_token = parse_qs(parsed.query).get("request_token", [None])[0]

if not request_token:
    request_token = input_val

try:
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]

    os.makedirs(os.path.dirname(ACCESS_TOKEN_FILE), exist_ok=True)
    with open(ACCESS_TOKEN_FILE, "w") as f:
        f.write(access_token)

    print(f"\n✅ Access token generated and saved to {ACCESS_TOKEN_FILE}")

except Exception as e:
    print("\n❌ Failed to generate token")
    print("Reason:", e)
