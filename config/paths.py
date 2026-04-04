import os

# ==================================================
# PROJECT ROOT (BigShotsCapital/)
# ==================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ==================================================
# FOLDERS
# ==================================================
CONFIG_DIR   = os.path.join(BASE_DIR, "config")
DB_DIR       = os.path.join(BASE_DIR, "database")
SUPPORT_DIR  = os.path.join(BASE_DIR, "support")
EXPORT_DIR   = os.path.join(BASE_DIR, "exports")
INFO_DIR     = os.path.join(BASE_DIR, "info")
MAIN_DIR     = os.path.join(BASE_DIR, "main")

# ==================================================
# ENSURE FOLDERS EXIST
# ==================================================
for _dir in [DB_DIR, SUPPORT_DIR, EXPORT_DIR, INFO_DIR]:
    os.makedirs(_dir, exist_ok=True)
