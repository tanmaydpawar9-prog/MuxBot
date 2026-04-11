from __future__ import annotations
import threading
import asyncio

from telethon import TelegramClient

from config import API_ID, API_HASH, BOT_TOKEN
from handlers.mux import register_mux_handlers
from handlers.subtitle import register_subtitle_handlers
from handlers.cache import register_cache_handlers
from handlers.speed import register_speed_handlers
from handlers.control import register_control_handlers
from utils.leech import start_server

state_store = {}
client = TelegramClient("bot", API_ID, API_HASH)

async def init():
    await client.start(bot_token=BOT_TOKEN)
    await register_mux_handlers(client, state_store)
    await register_subtitle_handlers(client, state_store)
    await register_cache_handlers(client, state_store)
    await register_speed_handlers(client, state_store)
    await register_control_handlers(client, state_store)

def main():
    import asyncio
from telethon import TelegramClient

from config import API_ID, API_HASH, BOT_TOKEN
from handlers.mux import register_mux_handlers
from handlers.subtitle import register_subtitle_handlers
from handlers.cache import register_cache_handlers
from handlers.speed import register_speed_handlers
from handlers.control import register_control_handlers
from utils.leech import start_server

state_store = {}

client = TelegramClient("bot", API_ID, API_HASH)

async def main():
    await client.start(bot_token=BOT_TOKEN)

    # ✅ Start leech server correctly
    await start_server()

    # ✅ Register handlers
    await register_mux_handlers(client, state_store)
    await register_subtitle_handlers(client, state_store)
    await register_cache_handlers(client, state_store)
    await register_speed_handlers(client, state_store)
    await register_control_handlers(client, state_store)

    print("Bot started...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
    client.loop.run_until_complete(init())
    client.run_until_disconnected()

if __name__ == "__main__":
    main()
