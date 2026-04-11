import asyncio
import os
import time
from pyrogram import Client
from pyrogram.types import Message
from utils.progress import ProgressTracker

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


async def download_media(
    client: Client,
    message: Message,
    status_msg: Message,
    cancel_flag: asyncio.Event,
    action: str = "Download",
) -> str | None:
    tracker = ProgressTracker()
    last_edit = [0.0]

    async def progress(current, total):
        if cancel_flag and cancel_flag.is_set():
            raise asyncio.CancelledError("Cancelled by user")
        now = time.time()
        if now - last_edit[0] < 4.0:
            return
        last_edit[0] = now
        text = tracker.render(action, current, total)
        if status_msg:
            try:
                await status_msg.edit_text(text, parse_mode="html")
            except Exception:
                pass

    try:
        path = await message.download(
            file_name=DOWNLOAD_DIR + "/",
            progress=progress,
        )
        return path
    except asyncio.CancelledError:
        return None
    except Exception as e:
        if status_msg:
            try:
                await status_msg.edit_text(f"❌ Download failed:\n<code>{e}</code>", parse_mode="html")
            except Exception:
                pass
        return None
