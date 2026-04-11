from config import AUTHORIZED_USERS, OWNER_ID

def is_authorized(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in AUTHORIZED_USERS
