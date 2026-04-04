from kiteconnect import KiteConnect
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
import time
import pyotp

# IMPORT FROM CONFIG
from config.kite_config import API_KEY, API_SECRET

# USER DETAILS
USER_ID = "your_user_id"
PASSWORD = "your_password"
TOTP_SECRET = "your_totp_secret"   # from Zerodha (base32 key)

kite = KiteConnect(api_key=API_KEY)

# Generate TOTP
totp = pyotp.TOTP(TOTP_SECRET).now()

# Setup browser
options = webdriver.ChromeOptions()
options.binary_location = "/usr/bin/chromium-browser"
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

service = Service("/usr/bin/chromedriver")
driver = webdriver.Chrome(service=service, options=options)

# Open login page
driver.get(kite.login_url())
time.sleep(3)

# Enter user + password
driver.find_element(By.ID, "userid").send_keys(USER_ID)
driver.find_element(By.ID, "password").send_keys(PASSWORD)
driver.find_element(By.XPATH, "//button[@type='submit']").click()

time.sleep(2)

# Enter TOTP (auto-generated)
driver.find_element(By.ID, "pin").send_keys(totp)
driver.find_element(By.XPATH, "//button[@type='submit']").click()

time.sleep(5)

# Extract request token
current_url = driver.current_url
request_token = current_url.split("request_token=")[1].split("&")[0]

# Generate access token
data = kite.generate_session(request_token, api_secret=API_SECRET)
access_token = data["access_token"]

# Save token
with open("/root/access_token.txt", "w") as f:
    f.write(access_token)

print("✅ Token generated")

driver.quit()