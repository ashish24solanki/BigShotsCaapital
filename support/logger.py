import os
from datetime import datetime

# =====================================================
# LOG FILE SETUP
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "strategy.log")

# =====================================================
# LOGGER
# =====================================================
def log(level, message, console=False):
    """
    level    : INFO | DEBUG | ERROR
    message  : log message
    console  : print to terminal if True
    """

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {message}"

    # ---- write to file (ALWAYS)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    # ---- optional console output
    if console:
        print(line)
