import os

def get_env_int(key: str, default: int = 0) -> int:
    val = os.environ.get(key, "").strip()
    return int(val) if val.isdigit() else default

API_ID = get_env_int("API_ID", 0)
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Access control
OWNER_ID = get_env_int("OWNER_ID", 0)
_allowed = os.environ.get("ALLOWED_USERS", "")
ALLOWED_USERS: set[int] = {
    int(uid.strip()) for uid in _allowed.split(",") if uid.strip().isdigit()
}

def is_allowed(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in ALLOWED_USERS
