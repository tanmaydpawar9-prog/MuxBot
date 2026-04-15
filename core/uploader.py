import asyncio
import time
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from utils.progress import ProgressTracker

CANCEL_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")
]])


async def upload_video(
    client: Client,
    chat_id: int,
    file_path: str,
    caption: str,
    thumb: str = None, # Path to thumbnail file
    status_message: Message = None, # The message to edit for progress updates
    cancel_flag: asyncio.Event = None,
    reply_to: int = None,
) -> Message | None:
    tracker = ProgressTracker()
    last_edit = [0.0]

    async def update_msg(text):
        try:
            await status_message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB)
        except Exception:
            pass

    async def progress(current, total):
        if cancel_flag and cancel_flag.is_set():
            raise asyncio.CancelledError("Cancelled by user")
        now = time.time()
        if now - last_edit[0] >= 1.0:
            last_edit[0] = now
            text = tracker.render("Upload", current, total)
            if status_message:
                asyncio.create_task(update_msg(text)) # Use asyncio.create_task to avoid blocking

    try:
        sent = await client.send_document(
            chat_id=chat_id,
            document=file_path,
            caption=caption,
            thumb=thumb,
            progress=progress,
            reply_to_message_id=reply_to,
        )
        return sent
    except asyncio.CancelledError:
        return None
    except Exception as e:
        if status_message:
            try:
                await status_message.edit_text(f"❌ Upload failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML) # Log the error
            except Exception as edit_e:
                logger.warning(f"Failed to edit status message after upload error: {edit_e}")
        return None
