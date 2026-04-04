"""
Kite Connection Helper
Centralized place to initialize Kite with proper token validation
"""

import os
import sys
import subprocess
from kiteconnect import KiteConnect

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.kite_config import API_KEY

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")


def get_access_token():
    """Load access token from file"""
    if os.path.exists(ACCESS_TOKEN_FILE):
        try:
            with open(ACCESS_TOKEN_FILE, "r") as f:
                token = f.read().strip()
                if token:
                    return token
        except Exception as e:
            print(f"⚠️ Error reading access token: {e}")
    return None


def validate_or_generate_token(kite):
    """Validate token or auto-generate via browser login"""
    token = get_access_token()

    if not token:
        print("\n⚠️ No access token found")
        print("🔐 Opening login in browser...\n")
        subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "generate_token.py")])
        # Restart after token is saved
        os.execv(sys.executable, [sys.executable] + sys.argv)

    kite.set_access_token(token)

    try:
        kite.profile()
        print("✅ Connected using valid access token")
        return kite
    except Exception as e:
        print(f"\n⚠️ Access token invalid or expired: {e}")
        print("🔄 Generating new token via browser...\n")
        subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "generate_token.py")])
        # Restart after token is saved
        os.execv(sys.executable, [sys.executable] + sys.argv)


def get_kite_connection():
    """
    Convenience function to get authenticated Kite instance
    
    Usage:
        from support.kite_helper import get_kite_connection
        kite = get_kite_connection()
    """
    kite = KiteConnect(api_key=API_KEY)
    return validate_or_generate_token(kite)


if __name__ == "__main__":
    # Test the connection
    print("\n🧪 Testing Kite connection...")
    kite = get_kite_connection()
    print(f"✅ Successfully connected to Kite API")
    print(f"   API Key: {API_KEY[:10]}...")
