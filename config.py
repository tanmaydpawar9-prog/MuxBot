import os

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
AUTHORIZED_USERS = [
    int(x) for x in os.getenv("AUTHORIZED_USERS", "").split()
    if x.strip().isdigit()
]

PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WORK_DIR = os.getenv("WORK_DIR", "work")
LEECH_DIR = os.getenv("LEECH_DIR", "leech")
CACHE_DIR = os.getenv("CACHE_DIR", "cache")
CACHE_INDEX = os.getenv("CACHE_INDEX", "cache/index.json")

MAX_TG_SIZE = 2 * 1024 * 1024 * 1024
CACHE_TTL = 2 * 60 * 60
HTTP_PORT = int(os.getenv("HTTP_PORT", "7860"))

SUB_TITLE_TAG = "ENGLISH @TheFrictionRealm"
