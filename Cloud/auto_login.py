from kiteconnect import KiteConnect
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

import time
import pyotp

# IMPORT FROM CONFIG
from config.kite_config import API_KEY, API_SECRET

# USER DETAILS
USER_ID = "BM5652"
PASSWORD = "Asus@F15"
TOTP_SECRET = "YWV5THHMMRDCH4ND55EH5ELWWDLD7KM5"   # from Zerodha (base32 key)

kite = KiteConnect(api_key=API_KEY)

# Generate TOTP
totp = pyotp.TOTP(TOTP_SECRET).now()
print("Generated TOTP:", totp)

# Setup browser
options = webdriver.ChromeOptions()
options.binary_location = "/usr/bin/google-chrome"
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--remote-debugging-port=9222")

service = Service(ChromeDriverManager().install())
print("Launching Browser...")
driver = webdriver.Chrome(service=service, options=options)
print("Browser Launched")

# Open login page
print("Opening login page...")
driver.get(kite.login_url())
time.sleep(3)

# Enter user + password
driver.find_element(By.ID, "userid").send_keys(USER_ID)
driver.find_element(By.ID, "password").send_keys(PASSWORD)
driver.find_element(By.XPATH, "//button[@type='submit']").click()
# Wait until next page loads

time.sleep(3)
print("Current URL after login:", driver.current_url)
print("Page title:", driver.title)

# Wait for TOTP input Field
print("Waiting for TOTP Field...")
totp_input = WebDriverWait(driver, 20).until(
    EC.presence_of_element_located((By.XPATH, "//input")))
print("Entering TOTP...")
totp_input.clear()
totp_input.send_keys(totp)
# Submit TOTP
print("TOTP entered - waiting for auto redirect......")

time.sleep(6)

print("After TOTP URL:", driver.current_url)
# Extract request token
current_url = driver.current_url
if "request_token=" not in current_url:
	print("? Login failed - request_token not found")
	print("Final URL:", current_url)
	driver.quit()
	exit()
request_token = current_url.split("request_token=")[1].split("&")[0]

# Generate access token
data = kite.generate_session(request_token, api_secret=API_SECRET)
access_token = data["access_token"]

# Save token
with open("/root/access_token.txt", "w") as f:
    f.write(access_token)

print("✅ Token generated")

driver.quit()