import asyncio
import os
import shutil
import threading
import logging
import secrets
import re
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import uvloop
    uvloop.install()
except ImportError:
    pass

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    Message, CallbackQuery,
)

import config
from config import is_allowed
from core import workflow
from core.downloader import download_media
from core.uploader import upload_video
from utils.caption import extract_caption
from utils.ffmpeg import mux_video, inject_style, convert_subtitle

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger("pyrogram").setLevel(logging.CRITICAL)
logging.getLogger("pyrogram.session.session").setLevel(logging.CRITICAL)
logging.getLogger("pyrogram.client").setLevel(logging.CRITICAL)
logging.getLogger("pyrogram.network").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Video Token Temp Storage
# ──────────────────────────────────────────────
SAVED_VIDEOS: dict[str, str] = {} # token -> path
SAVED_SUBS: dict[str, str] = {}   # token -> path
SAVED_THUMBS: dict[str, str] = {} # token -> path

async def _schedule_file_for_deletion(path: str, delay: int = 7200, token: str = None, saved_dict: dict = None):
    await asyncio.sleep(delay)
    if os.path.exists(path):
        try:
            os.remove(path)
            logger.info(f"Deleted scheduled file: {path}")
        except Exception:
            logger.warning(f"Failed to delete scheduled file {path}.")
    if token and saved_dict:
        # Only delete from dict if the path still matches
        if saved_dict.get(token) == path:
            del saved_dict[token]
            logger.info(f"Removed token {token} from {saved_dict.__name__}")

# Helper to delete bot messages
async def _delete_status_message(status_message: Message):
    if status_message:
        try:
            await status_message.delete()
            logger.debug(f"Deleted status message {status_message.id}")
        except Exception as e:
            logger.warning(f"Failed to delete status message {status_message.id}: {e}")

# ──────────────────────────────────────────────
# HF Keep-alive HTTP server on port 7860
# ──────────────────────────────────────────────
class _KA(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *_): pass

def _start_keepalive():
    server = HTTPServer(("0.0.0.0", 7860), _KA)
    threading.Thread(target=server.serve_forever, daemon=True).start()

# ──────────────────────────────────────────────
# Pyrogram client
# ──────────────────────────────────────────────
app = Client(
    "muxbot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    max_concurrent_transmissions=10,
)

# ──────────────────────────────────────────────
# Access guard
# ──────────────────────────────────────────────
def auth_only(func):
    async def wrapper(client, update, *args, **kwargs):
        uid = update.from_user.id if hasattr(update, "from_user") else 0
        if not is_allowed(uid):
            if isinstance(update, Message):
                await update.reply("⛔ Access denied.")
            return
        return await func(client, update, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

# ──────────────────────────────────────────────
# Cancel inline keyboard
# ──────────────────────────────────────────────
CANCEL_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")
]])

# ──────────────────────────────────────────────
# /start  /help
# ──────────────────────────────────────────────
@app.on_message(filters.command(["start", "help"]))
@auth_only
async def cmd_start(client, message: Message):
    await message.reply(
        "<b>🎬 MuxBot</b>\n\n"
        "<b>/mux</b> — Mux video + ASS subtitle\n"
        "<b>/style</b> — Style SRT/VTT/ASS subtitle\n"
        "<b>/convert</b> — Convert SRT/VTT/ASS\n\n"
        "Send /cancel at any time to abort.",
        parse_mode=ParseMode.HTML,
    )

# ──────────────────────────────────────────────
# /cancel command
# ──────────────────────────────────────────────
@app.on_message(filters.command("cancel"))
@auth_only
async def cmd_cancel(client, message: Message):
    uid = message.from_user.id
    workflow.cancel_user(uid)
    state = workflow.get_state(uid)
    status_message = state.get("status_message")
    await _delete_status_message(status_message)
    _cleanup_all_temp_for_user(uid) # New cleanup function
    workflow.clear_state(uid)
    await message.reply("❌ Operation cancelled.")

# ──────────────────────────────────────────────
# Cancel callback
# ──────────────────────────────────────────────
@app.on_callback_query(filters.regex("^cancel$"))
@auth_only
async def cb_cancel(client, cq: CallbackQuery):
    uid = cq.from_user.id
    workflow.cancel_user(uid)
    state = workflow.get_state(uid)
    status_message = state.get("status_message")
    await _delete_status_message(status_message)
    _cleanup_all_temp_for_user(uid) # New cleanup function
    workflow.clear_state(uid)
    await cq.message.edit_text("❌ Operation cancelled.")

# ──────────────────────────────────────────────
# ╔══════════════════════════════╗
# ║        /mux  FLOW           ║
# ╚══════════════════════════════╝
# ──────────────────────────────────────────────
@app.on_message(filters.command("mux"))
@auth_only
async def cmd_mux(client, message: Message):
    uid = message.from_user.id
    workflow.reset_cancel_flag(uid)
    workflow.clear_state(uid)
    status_message = await message.reply(
        "📹 <b>Step 1/4 — Send your video file.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )
    workflow.set_state(uid, flow="mux", step="await_video", status_message=status_message)

# ──────────────────────────────────────────────
# ╔══════════════════════════════╗
# ║       /reuse  FLOW           ║
# ╚══════════════════════════════╝
# ──────────────────────────────────────────────
@app.on_message(filters.command(["reuse", "reuser"]))
@auth_only
async def cmd_reuse(client, message: Message):
    uid = message.from_user.id
    if len(message.command) < 2:
        await message.reply("⚠️ Please provide a video token. Example: `/reuse abc1234`")
        return
    
    token = message.command[1]
    if token not in SAVED_VIDEOS or not os.path.exists(SAVED_VIDEOS[token]):
        await message.reply("❌ Invalid or expired video token.")
        return
        
    workflow.reset_cancel_flag(uid)
    workflow.clear_state(uid) # Clear previous state, but keep the status_message if it exists
    status_message = await message.reply(
        "♻️ <b>Video loaded from server!</b>\n\n📄 <b>Step 2/4 — Send your .ass subtitle file.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )
    workflow.set_state(uid, flow="mux", step="await_sub", video_dl_path=SAVED_VIDEOS[token], is_reused=True, status_message=status_message)


# ──────────────────────────────────────────────
# ╔══════════════════════════════╗
# ║       /style  FLOW          ║
# ╚══════════════════════════════╝
# ──────────────────────────────────────────────
@app.on_message(filters.command("style"))
@auth_only
async def cmd_style(client, message: Message):
    uid = message.from_user.id
    workflow.reset_cancel_flag(uid)
    workflow.clear_state(uid)
    status_message = await message.reply(
        "📄 <b>Step 1/2 — Send your .srt, .vtt, or .ass subtitle file.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )
    workflow.set_state(uid, flow="style", step="await_sub", status_message=status_message)

# ──────────────────────────────────────────────
# ╔══════════════════════════════╗
# ║      /convert  FLOW         ║
# ╚══════════════════════════════╝
# ──────────────────────────────────────────────
@app.on_message(filters.command("convert"))
@auth_only
async def cmd_convert(client, message: Message):
    uid = message.from_user.id
    workflow.reset_cancel_flag(uid)
    workflow.clear_state(uid)
    status_message = await message.reply(
        "📄 <b>Send your .srt, .vtt, or .ass file to convert.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )
    workflow.set_state(uid, flow="convert", step="await_sub", status_message=status_message)

# ──────────────────────────────────────────────
# /skip  (thumbnail skip in mux flow)
# ──────────────────────────────────────────────
@app.on_message(filters.command("skip"))
@auth_only
async def cmd_skip(client, message: Message):
    uid = message.from_user.id
    state = workflow.get_state(uid)
    if state.get("flow") == "mux" and state.get("step") == "await_thumb":
        status_message = state.get("status_message")
        await status_message.edit_text(
            "✏️ <b>Step 4/4 — Send the output filename</b> (without extension):",
            parse_mode=ParseMode.HTML,
            reply_markup=CANCEL_KB,
        )
        workflow.set_state(uid, thumb_msg=None, step="await_filename")
    else:
        await message.reply("Nothing to skip right now.")

# ──────────────────────────────────────────────
# Skip thumbnail callback
# ──────────────────────────────────────────────
@app.on_callback_query(filters.regex("^skip_thumb$"))
@auth_only
async def cb_skip_thumb(client, cq: CallbackQuery):
    uid = cq.from_user.id
    state = workflow.get_state(uid)
    if state.get("flow") == "mux" and state.get("step") == "await_thumb":
        workflow.set_state(uid, thumb_msg=None, step="await_filename")
        status_message = state.get("status_message")
        await status_message.edit_text(
            "✏️ <b>Step 4/4 — Send the output filename</b> (without extension):",
            parse_mode=ParseMode.HTML,
            reply_markup=CANCEL_KB,
        )
    else: # This case should ideally not happen if the button is only shown when appropriate
        await cq.answer("Nothing to skip right now.", show_alert=True)

# ──────────────────────────────────────────────
# Download Video First callback
# ──────────────────────────────────────────────
@app.on_callback_query(filters.regex("^dl_video_first$"))
@auth_only
async def cb_dl_video_first(client, cq: CallbackQuery):
    uid = cq.from_user.id
    state = workflow.get_state(uid)
    if state.get("flow") == "mux" and state.get("step") == "await_sub":
        video_msg = state.get("video_msg")
        if not video_msg:
            await cq.answer("Video message missing.", show_alert=True)
            return

        cancel = workflow.get_cancel_flag(uid)
        
        status_message = state.get("status_message")
        await status_message.edit_text("⬇️ Downloading video…", reply_markup=CANCEL_KB)
        now_str = datetime.now().strftime("%d_%m_%y_%I_%M_%p").lower()
        custom_video_name = f"video_{now_str}"
        
        path = await download_media(client, video_msg, status_message, cancel, "Download", custom_name=custom_video_name)
        if not path:
            return
            
        workflow.set_state(uid, video_dl_path=path)
        await status_message.edit_text(
            "✅ <b>Video downloaded!</b>\n\n📄 <b>Step 2/4 — Send your .ass subtitle file.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=CANCEL_KB
        )
    else:
        await cq.answer("Action not available right now.", show_alert=True)

# ──────────────────────────────────────────────
# Style mode keyboard callback
# ──────────────────────────────────────────────
@app.on_callback_query(filters.regex("^style_(cinematic|full4k)$"))
@auth_only
async def cb_style_mode(client, cq: CallbackQuery):
    uid = cq.from_user.id
    state = workflow.get_state(uid)
    if state.get("flow") != "style" or state.get("step") != "await_mode":
        await cq.answer("Not in style flow.", show_alert=True)
        return

    mode = cq.data.split("_", 1)[1]  # 'cinematic' or 'full4k'
    status_message = state.get("status_message")
    workflow.set_state(uid, mode=mode, step="processing", status_message=status_message)
    await cq.message.edit_text(f"⚙️ Applying <b>{'Cinematic 816p' if mode == 'cinematic' else 'Full 4K 1080p'}</b> style…", parse_mode=ParseMode.HTML)

    sub_path = state["sub"]
    out_path = sub_path.rsplit(".", 1)[0] + f"_{mode}.ass"
    cancel = workflow.get_cancel_flag(uid)

    logger.info(f"User {uid} applying style {mode} to {sub_path}")
    try:
        await inject_style(sub_path, out_path, mode)
    except Exception as e:
        logger.error(f"Style failed for user {uid}: {e}")
        await status_message.edit_text(f"❌ Failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML)
        _cleanup_all_temp_for_user(uid)
        workflow.clear_state(uid)
        return # Exit early on failure

    if cancel.is_set():
        _cleanup(sub_path, out_path)
        workflow.clear_state(uid)
        return

    await client.send_document(
        cq.message.chat.id,
        out_path,
        caption=f"✅ Styled subtitle ({mode})",
        reply_to_message_id=state.get("origin_msg_id"),
    ) # The bot's output file is uploaded here.
    
    # After successful upload, delete the local copy of the output file
    _cleanup(out_path)
    # Clean up temporary input files
    _cleanup_all_temp_for_user(uid)
    workflow.clear_state(uid)

# ──────────────────────────────────────────────
# Convert direction callback
# ──────────────────────────────────────────────
@app.on_callback_query(filters.regex(r"^conv_([a-z0-9]+2[a-z0-9]+)$"))
@auth_only
async def cb_convert_dir(client, cq: CallbackQuery):
    uid = cq.from_user.id
    state = workflow.get_state(uid)
    if state.get("flow") != "convert" or state.get("step") != "await_dir":
        await cq.answer("Not in convert flow.", show_alert=True)
        return

    direction = cq.data.split("_", 1)[1]
    src_ext, dst_ext = direction.split("2")
    sub_path = state["sub"]
    ext_in = os.path.splitext(sub_path)[1].lower().strip(".")

    # Validate direction matches file
    if src_ext != ext_in:
        await cq.answer(f"File is not .{src_ext}", show_alert=True)
        return

    status_message = state.get("status_message")
    out_ext = f".{dst_ext}"
    out_path = sub_path.rsplit(".", 1)[0] + "_converted" + out_ext
    await status_message.edit_text("⚙️ Converting…")

    logger.info(f"User {uid} converting {sub_path} direction {direction}")
    try:
        await convert_subtitle(sub_path, out_path)
    except Exception as e:
        logger.error(f"Conversion failed for user {uid}: {e}")
        await status_message.edit_text(f"❌ Failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML)
        # Clean up temporary input files
        _cleanup_all_temp_for_user(uid)
        workflow.clear_state(uid)
        return

    await client.send_document(
        cq.message.chat.id,
        out_path,
        caption=f"✅ Converted: {os.path.basename(out_path)}",
        reply_to_message_id=state.get("origin_msg_id"),
    ) # The bot's output file is uploaded here.

    # After successful upload, delete the local copy of the output file
    _cleanup(out_path)
    # Clean up temporary input files
    _cleanup_all_temp_for_user(uid)
    workflow.clear_state(uid)

# ──────────────────────────────────────────────
# Universal document/video/photo handler
# ──────────────────────────────────────────────
@app.on_message(filters.private & (filters.document | filters.video | filters.photo))
@auth_only
async def on_file(client, message: Message):
    uid = message.from_user.id
    state = workflow.get_state(uid)
    flow = state.get("flow")
    step = state.get("step")

    if not flow or not step:
        return

    status_message = state.get("status_message")
    cancel = workflow.get_cancel_flag(uid)
    if cancel.is_set():
        return

    # ── MUX FLOW ──────────────────────────────
    if flow == "mux":

        if step == "await_video":
            if not (message.video or (message.document and message.document.mime_type and "video" in message.document.mime_type)):
                await message.reply("⚠️ Please send a video file.")
                return
            
            # Delete the user's video message to keep chat clean
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Failed to delete user's video message {message.id}: {e}")

            # Check if there's a last used subtitle
            last_sub_token = state.get("last_sub_token")
            sub_reuse_kb = []
            if last_sub_token and SAVED_SUBS.get(last_sub_token) and os.path.exists(SAVED_SUBS[last_sub_token]):
                sub_reuse_kb.append([InlineKeyboardButton("📄 Use Last Subtitle", callback_data="uselast_sub")])

            reply_markup = InlineKeyboardMarkup(sub_reuse_kb + [
                [InlineKeyboardButton("⬇️ Download Video Now", callback_data="dl_video_first")],
                [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")]
            ])

            await status_message.edit_text(
                "📄 <b>Step 2/4 — Send your .ass subtitle file.</b>\n"
                "<i>(Files will download at the end, or click below to download the video now)</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            workflow.set_state(uid, video_msg=message, step="await_sub", is_reused=False)

        elif step == "await_sub":
            fname = _doc_name(message)
            if not fname.endswith(".ass"):
                await message.reply("⚠️ Please send an .ass subtitle file.")
                return

            # Delete the user's subtitle message
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Failed to delete user's subtitle message {message.id}: {e}")

            # Check for last used thumbnail
            last_thumb_token = state.get("last_thumb_token")
            thumb_reuse_kb = []
            if last_thumb_token and SAVED_THUMBS.get(last_thumb_token) and os.path.exists(SAVED_THUMBS[last_thumb_token]):
                thumb_reuse_kb.append([InlineKeyboardButton("🖼 Use Last Thumbnail", callback_data="uselast_thumb")])

            reply_markup = InlineKeyboardMarkup(thumb_reuse_kb + [
                [InlineKeyboardButton("⏭ Skip Thumbnail", callback_data="skip_thumb")],
                [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")]
            ])

            await status_message.edit_text(
                "🖼 <b>Step 3/4 — Send a thumbnail image or skip.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            workflow.set_state(uid, sub_msg=message, step="await_thumb")

        elif step == "await_thumb":
            workflow.set_state(uid, thumb_msg=message, step="await_filename")
            # Delete the user's thumbnail message
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Failed to delete user's thumbnail message {message.id}: {e}")

            await status_message.edit_text(
                "✏️ <b>Step 4/4 — Send the output filename</b> (without extension):",
                parse_mode=ParseMode.HTML,
                reply_markup=CANCEL_KB,
            )

    # ── STYLE FLOW ────────────────────────────
    elif flow == "style":
        if step == "await_sub":
            # Delete the user's subtitle message
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Failed to delete user's subtitle message {message.id}: {e}")

            fname = _doc_name(message)
            if not (fname.endswith(".srt") or fname.endswith(".ass") or fname.endswith(".vtt")):
                await message.reply("⚠️ Please send a .srt, .vtt, or .ass file.")
                return
            
            await status_message.edit_text("⬇️ Downloading subtitle…", reply_markup=CANCEL_KB)
            path = await download_media(client, message, status_message, cancel, "Download")
            if not path:
                _cleanup_all_temp_for_user(uid)
                workflow.clear_state(uid)
                return
            
            # Save this subtitle for potential reuse
            sub_token = secrets.token_hex(4)
            SAVED_SUBS[sub_token] = path
            asyncio.create_task(_schedule_file_for_deletion(path, 7200, sub_token, SAVED_SUBS))
            
            workflow.set_state(uid, sub=path, step="await_mode", origin_msg_id=message.id, last_sub_token=sub_token)
            await status_message.edit_text(
                "🎨 <b>Step 2/2 — Choose style mode:</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🎞 Cinematic (816p)", callback_data="style_cinematic"),
                        InlineKeyboardButton("📺 Full 4K (1080p)", callback_data="style_full4k"),
                    ],
                    [InlineKeyboardButton("📄 Use Last Subtitle", callback_data="uselast_sub")] if state.get("last_sub_token") and SAVED_SUBS.get(state["last_sub_token"]) and os.path.exists(SAVED_SUBS[state["last_sub_token"]]) else [],
                    [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")],
                ]),
            )

    # ── CONVERT FLOW ──────────────────────────
    elif flow == "convert":
        # Delete the user's subtitle message
        try:
            await message.delete()
        except Exception as e: logger.warning(f"Failed to delete user's subtitle message {message.id}: {e}")
        if step == "await_sub":
            fname = _doc_name(message)
            if not (fname.endswith(".srt") or fname.endswith(".ass") or fname.endswith(".vtt")):
                await message.reply("⚠️ Please send a .srt, .vtt, or .ass file.")
                return
            
            await status_message.edit_text("⬇️ Downloading subtitle…", reply_markup=CANCEL_KB)
            path = await download_media(client, message, status_message, cancel, "Download")
            if not path:
                _cleanup_all_temp_for_user(uid)
                workflow.clear_state(uid)
                return

            ext = os.path.splitext(fname)[1].lower().strip(".")
            # Auto-detect direction
            workflow.set_state(uid, sub=path, step="await_dir", origin_msg_id=message.id)
            buttons = []
            if ext != "srt":
                buttons.append([InlineKeyboardButton(f"{ext.upper()} → SRT", callback_data=f"conv_{ext}2srt")])
            if ext != "ass":
                buttons.append([InlineKeyboardButton(f"{ext.upper()} → ASS", callback_data=f"conv_{ext}2ass")])
            if ext != "vtt":
                buttons.append([InlineKeyboardButton(f"{ext.upper()} → VTT", callback_data=f"conv_{ext}2vtt")])
            buttons.append([InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")])

            await status.edit_text(
                "🔄 <b>Choose conversion direction:</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )


# ──────────────────────────────────────────────
# Text handler (filename step in mux flow)
# ──────────────────────────────────────────────
@app.on_message(filters.private & filters.text & ~filters.command(["start","help","mux","style","convert","cancel","skip","reuse","reuser"]))
@auth_only
async def on_text(client, message: Message):
    uid = message.from_user.id
    state = workflow.get_state(uid)
    if state.get("flow") == "mux" and state.get("step") == "await_filename":
        out_name = message.text.strip()
        out_name = re.sub(r'[\\/*?:"<>|]', "", out_name)
        if not out_name:
            await message.reply("⚠️ Please send a valid filename.")
            return

        status_message = state.get("status_message")
        is_reused = state.get("is_reused", False)
        video_path = state.get("video_dl_path")
        sub_path = None
        thumb_path = None
        out_path = f"downloads/{out_name}.mkv"

        status = await message.reply("⚙️ Preparing…", reply_markup=CANCEL_KB)
        # Delete user's filename message
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete user's filename message {message.id}: {e}")

        # Update the main status message to be the one we just sent
        workflow.set_state(uid, status_message=status)
        cancel = workflow.get_cancel_flag(uid)

        try:
            # 1. Download Video
            if not video_path:
                if is_reused:
                    await status.edit_text("❌ Error: Reused video path missing.", parse_mode=ParseMode.HTML)
                    return
                await status.edit_text("⬇️ Downloading video…", reply_markup=CANCEL_KB)
                video_path = await download_media(client, state["video_msg"], status, cancel, "Download", custom_name=f"{out_name}_video")
                if not video_path:
                    return
                workflow.set_state(uid, video_dl_path=video_path)

            # 2. Download Subtitle
            # Check if subtitle was already loaded via /uselast_sub
            sub_path = state.get("sub") # This is the path if /uselast_sub was used
            if not sub_path: # If not, download it
                await status.edit_text("⬇️ Downloading subtitle…", reply_markup=CANCEL_KB)
                sub_path = await download_media(client, state["sub_msg"], status, cancel, "Download", custom_name=f"{out_name}_sub")
                if not sub_path: return
                # Save this subtitle for potential reuse
                sub_token = secrets.token_hex(4)
                SAVED_SUBS[sub_token] = sub_path
                asyncio.create_task(_schedule_file_for_deletion(sub_path, 7200, sub_token, SAVED_SUBS))
                workflow.set_state(uid, sub=sub_path, last_sub_token=sub_token)

            # 3. Download Thumbnail
            # Check if thumbnail was already loaded via /uselast_thumb
            thumb_path = state.get("thumb_dl_path") # This is the path if /uselast_thumb was used
            if not thumb_path: # If not, download it
                if state.get("thumb_msg"):
                    await status.edit_text("⬇️ Downloading thumbnail…", reply_markup=CANCEL_KB)
                    thumb_path = await download_media(client, state["thumb_msg"], status, cancel, "Download", custom_name=f"{out_name}_thumb")
                    if not thumb_path: return
                    # Save this thumbnail for potential reuse
                    thumb_token = secrets.token_hex(4)
                    SAVED_THUMBS[thumb_token] = thumb_path
                    asyncio.create_task(_schedule_file_for_deletion(thumb_path, 7200, thumb_token, SAVED_THUMBS))
                    workflow.set_state(uid, thumb_dl_path=thumb_path, last_thumb_token=thumb_token)

            # 4. Mux
            await status.edit_text("⚙️ Muxing…", reply_markup=CANCEL_KB)
            logger.info(f"User {uid} started muxing {video_path} + {sub_path} -> {out_path}")
            await mux_video(video_path, sub_path, out_path, thumb_path)

            if cancel.is_set():
                return

            # 5. Upload
            caption = extract_caption(out_name + ".mkv")
            await status.edit_text("📤 Uploading…", reply_markup=CANCEL_KB)
            await upload_video(
                client,
                message.chat.id,
                out_path,
                caption=caption, # Caption is for the uploaded file
                thumb=thumb_path,
                status_msg=status,
                cancel_flag=cancel,
            )

            if cancel.is_set():
                return

            # Delete the local copy of the output file after successful upload
            _cleanup(out_path)

            # Token logic
            if not is_reused:
                token = secrets.token_hex(4)
                _, ext = os.path.splitext(video_path)
                saved_video_path = f"downloads/saved_{token}{ext}"
                try:
                    shutil.move(video_path, saved_video_path) # Use shutil.move for cross-device rename
                    SAVED_VIDEOS[token] = saved_video_path
                    asyncio.create_task(_schedule_file_for_deletion(saved_video_path, 7200, token, SAVED_VIDEOS))
                    video_path = saved_video_path
                except Exception:
                    token = None
            else:
                token = next((k for k, v in SAVED_VIDEOS.items() if v == video_path), None)
            
            if token:
                await client.send_message(
                    message.chat.id,
                    f"♻️ Video saved on server for 2 hours!\nTo reuse this video for another mux, use:\n<code>/reuse {token}</code>",
                    parse_mode=ParseMode.HTML
                )

            await _delete_status_message(status_message) # Delete the final status message

        except Exception as e:
            logger.error(f"Mux failed for user {uid}: {e}")
            if not cancel.is_set():
                await status.edit_text(f"❌ Mux failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML)
        finally:
            # Clean up temporary input files that are not saved for reuse
            _cleanup_all_temp_for_user(uid)
            # Delete the status message if it still exists (e.g., after an error)
            await _delete_status_message(status_message)
            workflow.clear_state(uid)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _cleanup_all_temp_for_user(uid: int):
    """Cleans up all temporary files associated with a user's current workflow state,
    excluding those explicitly saved for reuse."""
    state = workflow.get_state(uid)
    paths_to_clean = []

    # Paths that might have been downloaded
    if state.get("video_dl_path"):
        paths_to_clean.append(state["video_dl_path"])
    if state.get("sub"): # This is the downloaded sub path for style/convert
        paths_to_clean.append(state["sub"])
    if state.get("thumb_dl_path"): # This is the downloaded thumb path for mux
        paths_to_clean.append(state["thumb_dl_path"])

    for p in paths_to_clean:
        _cleanup(p) # Use the _cleanup function that checks against SAVED_ dicts

def _doc_name(message: Message) -> str:
    if message.document:
        return message.document.file_name or ""
    return ""
def _cleanup(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
                
    # New _cleanup logic:
    for p in paths:
        if p and os.path.exists(p):
            if p in SAVED_VIDEOS.values() or p in SAVED_SUBS.values() or p in SAVED_THUMBS.values():
                logger.debug(f"Skipping cleanup for saved file: {p}")
                continue
            try:
                os.remove(p)
                logger.info(f"Cleaned up temporary file: {p}")
            except Exception as e:
                logger.warning(f"Failed to delete temporary file {p}: {e}")

# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    _start_keepalive()
    logger.info("🚀 MuxBot starting…")
    app.run()
