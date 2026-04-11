from __future__ import annotations
from pathlib import Path
from telethon.tl.custom.message import Message

from config import MAX_TG_SIZE
from utils.progress import build_bar
from utils.cancel import register, pop

async def send_document(client, chat_id: int, file_path: str, caption: str | None = None, thumb: str | None = None, progress_message: Message | None = None, user_id: int | None = None):
    file_path = str(file_path)
    total = Path(file_path).stat().st_size
    start = __import__("time").time()

    async def progress(current, total_size):
        if progress_message:
            try:
                text = build_bar(current, total_size, start)
                await progress_message.edit(text)
            except Exception:
                pass

    try:
        if user_id is not None:
            # just keep a bookkeeping slot for cancellations
            register(user_id, register.__dict__.get("_task", None))
        return await client.send_file(
            chat_id,
            file_path,
            caption=caption,
            thumb=thumb,
            progress_callback=progress,
        )
    finally:
        if user_id is not None:
            pop(user_id)
