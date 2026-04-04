"""
Auto-login to Zerodha Kite and save access token.
Opens browser automatically for login.
"""

import os
import sys
import webbrowser
from kiteconnect import KiteConnect

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.kite_config import API_KEY, API_SECRET

# =====================================================
# FILE PATHS
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")

# =====================================================
# GENERATE TOKEN
# =====================================================
def generate_access_token():
    """Generate new access token via browser login"""
    print("\n" + "="*60)
    print("🔐 ZERODHA KITE LOGIN")
    print("="*60)
    
    kite = KiteConnect(api_key=API_KEY)
    login_url = kite.login_url()
    
    print(f"\n📱 Opening browser for login...")
    print(f"🔗 Login URL: {login_url}")
    
    # Auto-open browser
    try:
        webbrowser.open(login_url)
        print("✅ Browser opened (if not, visit the URL above)")
    except Exception as e:
        print(f"⚠️ Could not auto-open browser: {e}")
        print(f"📋 Please visit: {login_url}")
    
    # Wait for user to complete login
    print("\n⏳ Waiting for you to complete login in browser...")
    print("   After login, you'll see a callback URL with request_token\n")
    
    # Get request token
    raw_input = input("📝 Paste the request_token or callback URL: ").strip()
    if "request_token=" in raw_input:
        request_token = raw_input.split("request_token=")[1].split("&")[0]
    else:
        request_token = raw_input
    
    if not request_token:
        print("❌ Request token is required")
        sys.exit(1)
    
    try:
        # Exchange request token for access token
        print(f"\n🔄 Exchanging tokens...")
        data = kite.generate_session(request_token, api_secret=API_SECRET)
        access_token = data["access_token"]
        
        # Save token
        os.makedirs(os.path.dirname(ACCESS_TOKEN_FILE), exist_ok=True)
        with open(ACCESS_TOKEN_FILE, "w") as f:
            f.write(access_token)
        
        print(f"\n✅ SUCCESS! Access token saved to:")
        print(f"   {ACCESS_TOKEN_FILE}")
        print(f"\n✅ You can now run your scripts normally")
        
        return access_token
        
    except Exception as e:
        print(f"\n❌ Token exchange failed: {e}")
        print(f"   Make sure you copied the correct request_token")
        sys.exit(1)

# =====================================================
# MAIN
# =====================================================
if __name__ == "__main__":
    try:
        generate_access_token()
    except KeyboardInterrupt:
        print("\n\n⚠️ Login cancelled")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
