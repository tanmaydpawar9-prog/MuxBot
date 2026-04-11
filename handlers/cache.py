from __future__ import annotations
from telethon import events

from utils.access import is_authorized
from utils.cache import stats, purge

async def register_cache_handlers(client, state_store):
    @client.on(events.NewMessage(pattern=r"^/cache$"))
    async def cache_cmd(event):
        if not is_authorized(event.sender_id):
            return
        s = stats()
        removed, _ = purge()
        await event.reply(
            f"Cache entries: {s['count']}\n"
            f"Total size: {s['size']/1024/1024:.2f} MB\n"
            f"Purged: {removed}"
        )
