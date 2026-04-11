import asyncio
import os
import time
import math
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from utils.progress import ProgressTracker

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

CANCEL_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")
]])


async def download_media(
    client: Client,
    message: Message,
    status_msg: Message,
    cancel_flag: asyncio.Event,
    action: str = "Download",
    custom_name: str = None,
) -> str | None:
    tracker = ProgressTracker()
    last_edit = [0.0]

    media = message.document or message.video or message.audio or message.animation or message.photo
    if not media:
        return None
        
    file_size = getattr(media, "file_size", 0)
    orig_name = getattr(media, "file_name", "")
    ext = os.path.splitext(orig_name)[1] if orig_name else ".mp4"
    if not ext:
        ext = ".mp4"
        
    if custom_name:
        file_name = custom_name + ext
    else:
        file_name = orig_name if orig_name else f"file_{message.id}{ext}"

    output_path = os.path.join(DOWNLOAD_DIR, file_name)

    # Force fresh download to clear broken sparse files from previous versions
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass

    async def update_msg(text):
        try:
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB)
        except Exception:
            pass

    async def progress(current, total):
        if cancel_flag and cancel_flag.is_set():
            raise asyncio.CancelledError("Cancelled by user")
        now = time.time()
        if now - last_edit[0] >= 3.0:
            last_edit[0] = now
            text = tracker.render(action, current, total)
            if status_msg:
                asyncio.create_task(update_msg(text))

    try:
        path = await client.download_media(
            message,
            file_name=output_path,
            progress=progress,
        )
        return path
    except asyncio.CancelledError:
        return None
    except Exception as e:
        if status_msg:
            try:
                await status_msg.edit_text(f"❌ Download failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML)
            except Exception:
                pass
        return None
