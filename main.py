import asyncio
import os
import shutil
import threading
import logging
import secrets
import re
import json
import urllib.parse
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

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
PERMANENT_SUBS: dict[int, str] = {} # user_id -> path
PERMANENT_THUMBS: dict[int, str] = {} # user_id -> path
LAST_SUB_TOKENS: dict[int, str] = {}
LAST_THUMB_TOKENS: dict[int, str] = {}
SAVED_OUTPUTS: dict[str, str] = {} # token -> path

PERMANENT_DATA_FILE = "permanent_data.json"

def load_permanent_data():
    if os.path.exists(PERMANENT_DATA_FILE):
        try:
            with open(PERMANENT_DATA_FILE, "r") as f:
                data = json.load(f)
                PERMANENT_SUBS.update({int(k): v for k, v in data.get("subs", {}).items()})
                PERMANENT_THUMBS.update({int(k): v for k, v in data.get("thumbs", {}).items()})
        except Exception as e:
            logger.warning(f"Failed to load permanent data: {e}")

def save_permanent_data():
    try:
        with open(PERMANENT_DATA_FILE, "w") as f:
            json.dump({"subs": PERMANENT_SUBS, "thumbs": PERMANENT_THUMBS}, f)
    except Exception as e:
        logger.warning(f"Failed to save permanent data: {e}")

load_permanent_data()

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
        if saved_dict.get(token) == path: # This is for SAVED_VIDEOS, SAVED_SUBS, SAVED_THUMBS
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

# Helper to schedule text message deletion after a delay
async def _schedule_msg_for_deletion(message: Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass

# Helper to quickly delete a trigger command message
async def _del_cmd(message: Message):
    try:
        await message.delete()
    except Exception:
        pass

def _get_sub_kb(uid):
    kb = []
    if PERMANENT_SUBS.get(uid) and os.path.exists(PERMANENT_SUBS[uid]):
        kb.append([InlineKeyboardButton("📄 Use Permanent Subtitle", callback_data="use_permanent_sub")])
    last_sub_token = LAST_SUB_TOKENS.get(uid)
    if last_sub_token and SAVED_SUBS.get(last_sub_token) and os.path.exists(SAVED_SUBS[last_sub_token]):
        kb.append([InlineKeyboardButton("📄 Use Last Subtitle", callback_data="uselast_sub")])
    return kb

def _get_thumb_kb(uid):
    kb = []
    if PERMANENT_THUMBS.get(uid) and os.path.exists(PERMANENT_THUMBS[uid]):
        kb.append([InlineKeyboardButton("🖼 Use Permanent Thumbnail", callback_data="use_permanent_thumb")])
    last_thumb_token = LAST_THUMB_TOKENS.get(uid)
    if last_thumb_token and SAVED_THUMBS.get(last_thumb_token) and os.path.exists(SAVED_THUMBS[last_thumb_token]):
        kb.append([InlineKeyboardButton("🖼 Use Last Thumbnail", callback_data="uselast_thumb")])
    return kb

# ──────────────────────────────────────────────
# HF Keep-alive HTTP server on port 7860
# ──────────────────────────────────────────────
class _KA(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/dl/"):
            token = parsed.path.split("/")[-1]
            file_path = None
            if token in SAVED_VIDEOS: file_path = SAVED_VIDEOS[token]
            elif token in SAVED_SUBS: file_path = SAVED_SUBS[token]
            elif token in SAVED_THUMBS: file_path = SAVED_THUMBS[token]
            elif token in SAVED_OUTPUTS: file_path = SAVED_OUTPUTS[token]
            
            if file_path and os.path.exists(file_path):
                try:
                    self.send_response(200)
                    self.send_header("Content-type", "application/octet-stream")
                    self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(file_path)}"')
                    self.send_header("Content-Length", str(os.path.getsize(file_path)))
                    self.end_headers()
                    with open(file_path, "rb") as f:
                        shutil.copyfileobj(f, self.wfile)
                    return
                except Exception as e:
                    logger.error(f"HTTP Server Error: {e}")
                    return
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")
                return

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *_): pass

def _start_keepalive():
    server = ThreadingHTTPServer(("0.0.0.0", 7860), _KA)
    threading.Thread(target=server.serve_forever, daemon=True).start()

def get_base_url():
    space_host = os.environ.get("SPACE_HOST")
    if space_host: return f"https://{space_host}"
    space_id = os.environ.get("SPACE_ID")
    if space_id: return f"https://{space_id.replace('/', '-').lower()}.hf.space"
    return "http://127.0.0.1:7860"

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
    await _del_cmd(message)
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
    await _del_cmd(message)
    uid = message.from_user.id
    workflow.cancel_user(uid)
    state = workflow.get_state(uid)
    status_message = state.get("status_message")
    await _delete_status_message(status_message)
    _cleanup_all_temp_for_user(uid)
    workflow.clear_state(uid)
    
    # Self-deleting cancellation message since we keep chat clean
    temp_msg = await message.reply("❌ Operation cancelled.")
    asyncio.create_task(_schedule_msg_for_deletion(temp_msg, 5))

# ──────────────────────────────────────────────
# Cancel callback
# ──────────────────────────────────────────────
@app.on_callback_query(filters.regex("^cancel$"))
@auth_only
async def cb_cancel(client, cq: CallbackQuery):
    uid = cq.from_user.id
    msg_id = cq.message.id
    workflow.cancel_msg(msg_id)
    
    state = workflow.get_state(uid)
    if state.get("status_message") and state["status_message"].id == msg_id:
        _cleanup_all_temp_for_user(uid)
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
    await _del_cmd(message)
    uid = message.from_user.id
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
    await _del_cmd(message)
    uid = message.from_user.id
    if len(message.command) < 2:
        await message.reply("⚠️ Please provide a video token. Example: `/reuse abc1234`")
        return
    
    token = message.command[1]
    if token not in SAVED_VIDEOS or not os.path.exists(SAVED_VIDEOS[token]):
        await message.reply("❌ Invalid or expired video token.")
        return
        
    workflow.clear_state(uid)
    workflow.set_state(uid, flow="mux", step="await_sub", video_dl_path=SAVED_VIDEOS[token], is_reused=True)
    status_message = await message.reply(
        "♻️ <b>Video loaded from server!</b>\n\n📄 <b>Step 2/4 — Send your .ass subtitle file.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(_get_sub_kb(uid) + [[InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")]]),
    )
    workflow.set_state(uid, status_message=status_message)


# ──────────────────────────────────────────────
# ╔══════════════════════════════╗
# ║       /style  FLOW          ║
# ╚══════════════════════════════╝
# ──────────────────────────────────────────────
@app.on_message(filters.command("style"))
@auth_only
async def cmd_style(client, message: Message):
    await _del_cmd(message)
    uid = message.from_user.id
    workflow.clear_state(uid)
    status_message = await message.reply(
        "📄 <b>Step 1/2 — Send your .srt, .vtt, or .ass subtitle file.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(_get_sub_kb(uid) + [[InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")]]),
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
    await _del_cmd(message)
    uid = message.from_user.id
    workflow.clear_state(uid)
    status_message = await message.reply(
        "📄 <b>Send your .srt, .vtt, or .ass file to convert.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(_get_sub_kb(uid) + [[InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")]]),
    )
    workflow.set_state(uid, flow="convert", step="await_sub", status_message=status_message)

# ──────────────────────────────────────────────
# /skip  (thumbnail skip in mux flow)
# ──────────────────────────────────────────────
@app.on_message(filters.command("skip"))
@auth_only
async def cmd_skip(client, message: Message):
    await _del_cmd(message)
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
# /thumb command (set permanent thumbnail)
# ──────────────────────────────────────────────
@app.on_message(filters.command("thumb"))
@auth_only
async def cmd_set_thumb(client, message: Message):
    await _del_cmd(message)
    uid = message.from_user.id
    workflow.clear_state(uid)
    status_message = await message.reply(
        "🖼 <b>Send the image you want to set as your permanent thumbnail.</b>\n"
        "<i>This will be used automatically in /mux unless overridden.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )
    workflow.set_state(uid, flow="set_thumb", step="await_thumb_file", status_message=status_message)

# ──────────────────────────────────────────────
# /sub command (set permanent subtitle)
# ──────────────────────────────────────────────
@app.on_message(filters.command("sub"))
@auth_only
async def cmd_set_sub(client, message: Message):
    await _del_cmd(message)
    uid = message.from_user.id
    workflow.clear_state(uid)
    status_message = await message.reply(
        "📄 <b>Send the .ass subtitle file you want to set as your permanent subtitle.</b>\n"
        "<i>This will be used automatically in /mux, /style, /convert unless overridden.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )
    workflow.set_state(uid, flow="set_sub", step="await_sub_file", status_message=status_message)

# ──────────────────────────────────────────────
# Use Permanent Subtitle callback
# ──────────────────────────────────────────────
@app.on_callback_query(filters.regex("^use_permanent_sub$"))
@auth_only
async def cb_use_permanent_sub(client, cq: CallbackQuery):
    await _handle_use_permanent_file(client, cq, "sub")

# ──────────────────────────────────────────────
# Use Permanent Thumbnail callback
# ──────────────────────────────────────────────
@app.on_callback_query(filters.regex("^use_permanent_thumb$"))
@auth_only
async def cb_use_permanent_thumb(client, cq: CallbackQuery):
    await _handle_use_permanent_file(client, cq, "thumb")

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

        status_message = state.get("status_message")
        cancel = workflow.get_cancel_flag(uid, status_message.id)
        
        await status_message.edit_text("⬇️ Downloading video…", reply_markup=CANCEL_KB)
        now_str = datetime.now().strftime("%d_%m_%y_%I_%M_%p").lower()
        custom_video_name = f"video_{now_str}"
        
        path = await download_media(client, video_msg, status_message, cancel, "Download", custom_name=custom_video_name)
        if not path:
            return
            
        token = secrets.token_hex(4)
        _, ext = os.path.splitext(path)
        saved_video_path = f"downloads/saved_{token}{ext}"
        try:
            shutil.move(path, saved_video_path)
            SAVED_VIDEOS[token] = saved_video_path
            asyncio.create_task(_schedule_file_for_deletion(saved_video_path, 7200, token, SAVED_VIDEOS))
                base_url = get_base_url()
            reuse_msg = await client.send_message(
                cq.message.chat.id,
                    f"♻️ Video downloaded and saved on server for 2 hours!\nTo reuse this video for another mux, use:\n<code>/reuse {token}</code>\n🔗 <b>Download Link:</b> {base_url}/dl/{token}",
                parse_mode=ParseMode.HTML
            )
            asyncio.create_task(_schedule_msg_for_deletion(reuse_msg, 7200))
            workflow.set_state(uid, video_dl_path=saved_video_path, is_reused=True)
        except Exception as e:
            logger.warning(f"Failed to save video for reuse: {e}")
            workflow.set_state(uid, video_dl_path=path)

        reply_markup = InlineKeyboardMarkup(_get_sub_kb(uid) + [
            [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")]
        ])
        await status_message.edit_text(
            "✅ <b>Video downloaded!</b>\n\n📄 <b>Step 2/4 — Send your .ass subtitle file.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
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
    cancel = workflow.get_cancel_flag(uid, status_message.id)

    logger.info(f"User {uid} applying style {mode} to {sub_path}")
    try:
        await inject_style(sub_path, out_path, mode)
    except Exception as e:
        logger.error(f"Style failed for user {uid}: {e}")
        await status_message.edit_text(f"❌ Failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML)
        _cleanup_all_temp_for_user(uid)
        workflow.clear_cancel_flag(uid, status_message.id)
        workflow.clear_state(uid)
        return # Exit early on failure

    if cancel.is_set():
        _cleanup(sub_path, out_path)
        workflow.clear_cancel_flag(uid, status_message.id)
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
    workflow.clear_cancel_flag(uid, status_message.id)
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
    cancel = workflow.get_cancel_flag(uid, status_message.id)
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
        workflow.clear_cancel_flag(uid, status_message.id)
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
    workflow.clear_cancel_flag(uid, status_message.id)
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
    cancel = workflow.get_cancel_flag(uid, status_message.id)
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

            reply_markup = InlineKeyboardMarkup(_get_sub_kb(uid) + [
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

            reply_markup = InlineKeyboardMarkup(_get_thumb_kb(uid) + [
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
            LAST_SUB_TOKENS[uid] = sub_token
            
            workflow.set_state(uid, sub=path, step="await_mode", origin_msg_id=message.id, last_sub_token=sub_token)
            await status_message.edit_text(
                "🎨 <b>Step 2/2 — Choose style mode:</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🎞 Cinematic (816p)", callback_data="style_cinematic"),
                        InlineKeyboardButton("📺 Full 4K (1080p)", callback_data="style_full4k"),
                    ],
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
            sub_token = secrets.token_hex(4)
            SAVED_SUBS[sub_token] = path
            asyncio.create_task(_schedule_file_for_deletion(path, 7200, sub_token, SAVED_SUBS))
            LAST_SUB_TOKENS[uid] = sub_token

            workflow.set_state(uid, sub=path, step="await_dir", origin_msg_id=message.id)
            buttons = []
            if ext != "srt":
                buttons.append([InlineKeyboardButton(f"{ext.upper()} → SRT", callback_data=f"conv_{ext}2srt")])
            if ext != "ass":
                buttons.append([InlineKeyboardButton(f"{ext.upper()} → ASS", callback_data=f"conv_{ext}2ass")])
            if ext != "vtt":
                buttons.append([InlineKeyboardButton(f"{ext.upper()} → VTT", callback_data=f"conv_{ext}2vtt")])

            buttons.append([InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")])

            await status_message.edit_text( # Corrected to use status_message
                "🔄 <b>Choose conversion direction:</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )

    # ── SET PERMANENT THUMBNAIL FLOW ──────────
    elif flow == "set_thumb":
        if step == "await_thumb_file":
            if not (message.photo or (message.document and message.document.mime_type and "image" in message.document.mime_type)):
                await message.reply("⚠️ Please send an image file for the thumbnail.")
                return
            
            await status_message.edit_text("⬇️ Downloading thumbnail…", reply_markup=CANCEL_KB)
            path = await download_media(client, message, status_message, cancel, "Download", custom_name=f"permanent_thumb_{uid}")
            if not path:
                _cleanup_all_temp_for_user(uid)
                workflow.clear_state(uid)
                return
            
            # Delete old permanent thumbnail if exists
            if PERMANENT_THUMBS.get(uid) and os.path.exists(PERMANENT_THUMBS[uid]):
                _cleanup(PERMANENT_THUMBS[uid])

            logger.info(f"User {uid} set permanent thumbnail: {path}")
            PERMANENT_THUMBS[uid] = path
            save_permanent_data()
            workflow.clear_state(uid)
            await status_message.edit_text("✅ <b>Permanent thumbnail set!</b>", parse_mode=ParseMode.HTML)

    # ── SET PERMANENT SUBTITLE FLOW ──────────
    elif flow == "set_sub":
        if step == "await_sub_file":
            fname = _doc_name(message)
            if not fname.endswith(".ass"):
                await message.reply("⚠️ Please send an .ass subtitle file.")
                return
            
            # Delete the user's message
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Failed to delete user's message {message.id}: {e}")

            await status_message.edit_text("⬇️ Downloading subtitle…", reply_markup=CANCEL_KB)
            path = await download_media(client, message, status_message, cancel, "Download", custom_name=f"permanent_sub_{uid}")
            if not path:
                _cleanup_all_temp_for_user(uid)
                workflow.clear_state(uid)
                return
            
            # Delete old permanent subtitle if exists
            if PERMANENT_SUBS.get(uid) and os.path.exists(PERMANENT_SUBS[uid]):
                _cleanup(PERMANENT_SUBS[uid])

            logger.info(f"User {uid} set permanent subtitle: {path}")
            PERMANENT_SUBS[uid] = path
            save_permanent_data()
            workflow.clear_state(uid)
            await status_message.edit_text("✅ <b>Permanent subtitle set!</b>", parse_mode=ParseMode.HTML)


# ──────────────────────────────────────────────
# Helper for using permanent files
# ──────────────────────────────────────────────
async def _handle_use_permanent_file(client, cq: CallbackQuery, file_type: str):
    """Helper function to handle 'use permanent' callbacks."""
    uid = cq.from_user.id
    state = workflow.get_state(uid)
    status_message = state.get("status_message")

    permanent_dict = PERMANENT_SUBS if file_type == "sub" else PERMANENT_THUMBS
    state_key = "sub" if file_type == "sub" else "thumb_dl_path"
    
    if not permanent_dict.get(uid) or not os.path.exists(permanent_dict[uid]):
        await cq.answer(f"No permanent {file_type} found or it has been deleted.", show_alert=True)
        return

    file_path = permanent_dict[uid]
    workflow.set_state(uid, **{state_key: file_path})

    if file_type == "sub":
        # For mux flow, move to await_thumb
        if state.get("flow") == "mux":
            reply_markup = InlineKeyboardMarkup(_get_thumb_kb(uid) + [
                [InlineKeyboardButton("⏭ Skip Thumbnail", callback_data="skip_thumb")],
                [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")]
            ])
            await status_message.edit_text("✅ <b>Permanent subtitle loaded!</b>\n\n🖼 <b>Step 3/4 — Send a thumbnail image or skip.</b>", parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            workflow.set_state(uid, step="await_thumb")
        # For style/convert flow, move to await_mode/await_dir (re-render buttons)
        elif state.get("flow") == "style":
            # This part needs to re-render the style mode buttons, similar to on_file for style flow
            await status_message.edit_text("✅ <b>Permanent subtitle loaded!</b>\n\n🎨 <b>Step 2/2 — Choose style mode:</b>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎞 Cinematic (816p)", callback_data="style_cinematic"), InlineKeyboardButton("📺 Full 4K (1080p)", callback_data="style_full4k")],
                [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")],
            ]))
            workflow.set_state(uid, step="await_mode")
        elif state.get("flow") == "convert":
            # This part needs to re-render the convert direction buttons, similar to on_file for convert flow
            # For simplicity, we'll just move to the next step and let the user re-trigger if needed, or re-implement button logic here
            await status_message.edit_text("✅ <b>Permanent subtitle loaded!</b>\n\n🔄 <b>Choose conversion direction:</b>", parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB)
            workflow.set_state(uid, step="await_dir") # User will need to send a new command or re-select
    elif file_type == "thumb":
        await status_message.edit_text("✅ <b>Permanent thumbnail loaded!</b>\n\n✏️ <b>Step 4/4 — Send the output filename</b> (without extension):", parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB)
        workflow.set_state(uid, step="await_filename")
    await cq.answer(f"Permanent {file_type} loaded!", show_alert=False)

# ──────────────────────────────────────────────
# /uselast_sub command
# ──────────────────────────────────────────────
@app.on_callback_query(filters.regex("^uselast_sub$"))
@auth_only
async def cb_uselast_sub(client, cq: CallbackQuery):
    uid = cq.from_user.id
    state = workflow.get_state(uid)
    status_message = state.get("status_message")
    
    if PERMANENT_SUBS.get(uid) and os.path.exists(PERMANENT_SUBS[uid]):
        await cq.answer("A permanent subtitle is already set. Use that or upload a new one.", show_alert=True)
        return
    
    last_sub_token = LAST_SUB_TOKENS.get(uid)
    if not last_sub_token or not SAVED_SUBS.get(last_sub_token) or not os.path.exists(SAVED_SUBS[last_sub_token]):
        await cq.answer("No last subtitle found or it has expired.", show_alert=True)
        return

    sub_path = SAVED_SUBS[last_sub_token]
    
    # Update state based on current flow
    flow = state.get("flow")
    
    # Check for permanent thumbnail (for mux flow only)
    permanent_thumb_kb = []
    if PERMANENT_THUMBS.get(uid) and os.path.exists(PERMANENT_THUMBS[uid]):
        permanent_thumb_kb.append([InlineKeyboardButton("🖼 Use Permanent Thumbnail", callback_data="use_permanent_thumb")])
    
    if flow == "mux":
        workflow.set_state(uid, sub=sub_path, step="await_thumb")
        reply_markup = InlineKeyboardMarkup(_get_thumb_kb(uid) + [
            [InlineKeyboardButton("⏭ Skip Thumbnail", callback_data="skip_thumb")],
            [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")]
        ])
        await status_message.edit_text(
            "✅ <b>Last subtitle loaded!</b>\n\n🖼 <b>Step 3/4 — Send a thumbnail image or skip.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    elif flow == "style":
        workflow.set_state(uid, sub=sub_path, step="await_mode", origin_msg_id=cq.message.id)
        await status_message.edit_text(
            "✅ <b>Last subtitle loaded!</b>\n\n🎨 <b>Step 2/2 — Choose style mode:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎞 Cinematic (816p)", callback_data="style_cinematic"),
                    InlineKeyboardButton("📺 Full 4K (1080p)", callback_data="style_full4k"),
                ],
                [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")],
            ]),
        )
    elif flow == "convert":
        # This flow needs to determine conversion directions based on the sub_path's extension
        ext = os.path.splitext(sub_path)[1].lower().strip(".")
        buttons = []
        if ext != "srt":
            buttons.append([InlineKeyboardButton(f"{ext.upper()} → SRT", callback_data=f"conv_{ext}2srt")])
        if ext != "ass":
            buttons.append([InlineKeyboardButton(f"{ext.upper()} → ASS", callback_data=f"conv_{ext}2ass")])
        if ext != "vtt":
            buttons.append([InlineKeyboardButton(f"{ext.upper()} → VTT", callback_data=f"conv_{ext}2vtt")])
        buttons.append([InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")])

        workflow.set_state(uid, sub=sub_path, step="await_dir", origin_msg_id=cq.message.id)
        await status_message.edit_text(
            "✅ <b>Last subtitle loaded!</b>\n\n🔄 <b>Choose conversion direction:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    else:
        await cq.answer("Cannot use last subtitle in this context.", show_alert=True)

# ──────────────────────────────────────────────
# /uselast_thumb command
# ──────────────────────────────────────────────
@app.on_callback_query(filters.regex("^uselast_thumb$"))
@auth_only
async def cb_uselast_thumb(client, cq: CallbackQuery):
    uid = cq.from_user.id
    state = workflow.get_state(uid)
    status_message = state.get("status_message")
    
    if PERMANENT_THUMBS.get(uid) and os.path.exists(PERMANENT_THUMBS[uid]):
        await cq.answer("A permanent thumbnail is already set. Use that or upload a new one.", show_alert=True)
        return
    
    last_thumb_token = LAST_THUMB_TOKENS.get(uid)
    if not last_thumb_token or not SAVED_THUMBS.get(last_thumb_token) or not os.path.exists(SAVED_THUMBS[last_thumb_token]):
        await cq.answer("No last thumbnail found or it has expired.", show_alert=True)
        return

    thumb_path = SAVED_THUMBS[last_thumb_token]
    workflow.set_state(uid, thumb_msg=None, thumb_dl_path=thumb_path, step="await_filename") # Store path directly
    await status_message.edit_text(
        "✅ <b>Last thumbnail loaded!</b>\n\n✏️ <b>Step 4/4 — Send the output filename</b> (without extension):",
        parse_mode=ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )

# ──────────────────────────────────────────────
# /clear command
# ──────────────────────────────────────────────
@app.on_message(filters.command("clear"))
@auth_only
async def cmd_clear(client, message: Message):
    await _del_cmd(message)
    uid = message.from_user.id
    state = workflow.get_state(uid)
    status_message = state.get("status_message")
    await _delete_status_message(status_message)
    _cleanup_all_temp_for_user(uid) # Do not clear permanent files
    workflow.clear_state(uid)
    temp_msg = await message.reply("🗑️ All temporary data and state cleared.")
    asyncio.create_task(_schedule_msg_for_deletion(temp_msg, 5))

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
        # Sanitize filename to remove invalid characters
        out_name = re.sub(r'[\\/*?:"<>|]', "", out_name) # Sanitize filename
        if not out_name:
            await message.reply("⚠️ Please send a valid filename.")
            return

        status = state.get("status_message") # This is the message we will edit
        if not status: # Safety check in case the message was deleted
            status = await message.reply("...", reply_markup=CANCEL_KB)
            workflow.set_state(uid, status_message=status)

        is_reused = state.get("is_reused", False)
        video_path = state.get("video_dl_path")
        sub_path = None
        thumb_path = None
        out_path = f"downloads/{out_name}.mkv"

        await status.edit_text("⚙️ Preparing…", reply_markup=CANCEL_KB)
        cancel = workflow.get_cancel_flag(uid, status.id)

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

            # 2. Download Subtitle (or use existing)
            if not sub_path and PERMANENT_SUBS.get(uid) and os.path.exists(PERMANENT_SUBS[uid]):
                sub_path = PERMANENT_SUBS[uid]
                workflow.set_state(uid, sub=sub_path)
            sub_path = state.get("sub")
            if not sub_path: # If not, download it
                await status.edit_text("⬇️ Downloading subtitle…", reply_markup=CANCEL_KB)
                sub_path = await download_media(client, state["sub_msg"], status, cancel, "Download", custom_name=f"{out_name}_sub")
                if not sub_path: return
                # Save this subtitle for potential reuse
                sub_token = secrets.token_hex(4)
                SAVED_SUBS[sub_token] = sub_path
                asyncio.create_task(_schedule_file_for_deletion(sub_path, 7200, sub_token, SAVED_SUBS))
                LAST_SUB_TOKENS[uid] = sub_token

            # 3. Download Thumbnail (or use existing)
            if not thumb_path and PERMANENT_THUMBS.get(uid) and os.path.exists(PERMANENT_THUMBS[uid]):
                thumb_path = PERMANENT_THUMBS[uid]
                workflow.set_state(uid, thumb_dl_path=thumb_path)
            thumb_path = state.get("thumb_dl_path")
            if not thumb_path: # If not, download it
                if state.get("thumb_msg"):
                    await status.edit_text("⬇️ Downloading thumbnail…", reply_markup=CANCEL_KB)
                    thumb_path = await download_media(client, state["thumb_msg"], status, cancel, "Download", custom_name=f"{out_name}_thumb")
                    if not thumb_path: return
                    # Save this thumbnail for potential reuse
                    thumb_token = secrets.token_hex(4)
                    SAVED_THUMBS[thumb_token] = thumb_path
                    asyncio.create_task(_schedule_file_for_deletion(thumb_path, 7200, thumb_token, SAVED_THUMBS))
                    LAST_THUMB_TOKENS[uid] = thumb_token

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
                status_message=status,
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
                base_url = get_base_url()
                reuse_msg = await client.send_message(
                    message.chat.id,
                    f"♻️ Video saved on server for 2 hours!\nTo reuse this video for another mux, use:\n<code>/reuse {token}</code>\n🔗 <b>Download Link:</b> {base_url}/dl/{token}",
                    parse_mode=ParseMode.HTML
                )
                asyncio.create_task(_schedule_msg_for_deletion(reuse_msg, 7200))

            await _delete_status_message(status) # Delete the progress message

        except Exception as e:
            logger.error(f"Mux failed for user {uid}: {e}")
            if not cancel.is_set():
                await status.edit_text(f"❌ Mux failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML)
        finally:
            # Clean up temporary input files that are not saved for reuse (including permanent ones)
            _cleanup_all_temp_for_user(uid)
            # Delete the status message if it still exists (e.g., after an error)
            await _delete_status_message(status) # Use the status message from the try block
            workflow.clear_cancel_flag(uid, status.id)
            workflow.clear_state(uid)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _doc_name(message: Message) -> str:
    if message.document:
        return message.document.file_name or ""
    return ""

async def _handle_use_permanent_file(client, cq: CallbackQuery, file_type: str):
    """Helper function to handle 'use permanent' callbacks."""
    uid = cq.from_user.id
    state = workflow.get_state(uid)
    status_message = state.get("status_message")

    permanent_dict = PERMANENT_SUBS if file_type == "sub" else PERMANENT_THUMBS
    state_key = "sub" if file_type == "sub" else "thumb_dl_path"
    
    if not permanent_dict.get(uid) or not os.path.exists(permanent_dict[uid]):
        await cq.answer(f"No permanent {file_type} found or it has been deleted.", show_alert=True)
        return

    file_path = permanent_dict[uid]
    workflow.set_state(uid, **{state_key: file_path})

    if file_type == "sub":
        # For mux flow, move to await_thumb
        if state.get("flow") == "mux":
            reply_markup = InlineKeyboardMarkup(_get_thumb_kb(uid) + [
                [InlineKeyboardButton("⏭ Skip Thumbnail", callback_data="skip_thumb")],
                [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")]
            ])
            await status_message.edit_text("✅ <b>Permanent subtitle loaded!</b>\n\n🖼 <b>Step 3/4 — Send a thumbnail image or skip.</b>", parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            workflow.set_state(uid, step="await_thumb")
        # For style/convert flow, move to await_mode/await_dir (re-render buttons)
        elif state.get("flow") == "style":
            # This part needs to re-render the style mode buttons, similar to on_file for style flow
            await status_message.edit_text("✅ <b>Permanent subtitle loaded!</b>\n\n🎨 <b>Step 2/2 — Choose style mode:</b>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎞 Cinematic (816p)", callback_data="style_cinematic"), InlineKeyboardButton("📺 Full 4K (1080p)", callback_data="style_full4k")],
                [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")],
            ]))
            workflow.set_state(uid, step="await_mode")
        elif state.get("flow") == "convert":
            # This part needs to re-render the convert direction buttons, similar to on_file for convert flow
            # For simplicity, we'll just move to the next step and let the user re-trigger if needed, or re-implement button logic here
            await status_message.edit_text("✅ <b>Permanent subtitle loaded!</b>\n\n🔄 <b>Choose conversion direction:</b>", parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB)
            workflow.set_state(uid, step="await_dir") # User will need to send a new command or re-select
    elif file_type == "thumb":
        await status_message.edit_text("✅ <b>Permanent thumbnail loaded!</b>\n\n✏️ <b>Step 4/4 — Send the output filename</b> (without extension):", parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB)
        workflow.set_state(uid, step="await_filename")
    await cq.answer(f"Permanent {file_type} loaded!", show_alert=False)

def _cleanup(*paths):
    for p in paths:
        if p and os.path.exists(p):
            if p in SAVED_VIDEOS.values() or p in SAVED_SUBS.values() or p in SAVED_THUMBS.values() or \
               p in PERMANENT_SUBS.values() or p in PERMANENT_THUMBS.values() or p in SAVED_OUTPUTS.values():
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


# ──────────────────────────────────────────────
# Text handler (filename step in mux flow)
# ──────────────────────────────────────────────
@app.on_message(filters.private & filters.text & ~filters.command(["start","help","mux","style","convert","cancel","skip","reuse","reuser", "thumb", "sub", "clear"]))
@auth_only
async def on_text(client, message: Message):
    uid = message.from_user.id
    state = workflow.get_state(uid)
    if state.get("flow") == "mux" and state.get("step") == "await_filename":
        out_name = message.text.strip()
        # Sanitize filename to remove invalid characters
        out_name = re.sub(r'[\\/*?:"<>|]', "", out_name)
        if not out_name:
            await message.reply("⚠️ Please send a valid filename.")
            return

        status = state.get("status_message") # This is the message we will edit
        if not status: # Safety check in case the message was deleted
            status = await message.reply("⚙️ Preparing…", reply_markup=CANCEL_KB)
            workflow.set_state(uid, status_message=status)
        else:
            await status.edit_text("⚙️ Preparing…", reply_markup=CANCEL_KB)

        is_reused = state.get("is_reused", False)
        video_path = state.get("video_dl_path")
        sub_path = None
        thumb_path = None
        out_path = f"downloads/{out_name}.mkv"

        cancel = workflow.get_cancel_flag(uid, status.id)

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

            # 2. Download Subtitle (or use existing)
            if not sub_path and PERMANENT_SUBS.get(uid) and os.path.exists(PERMANENT_SUBS[uid]):
                sub_path = PERMANENT_SUBS[uid]
                workflow.set_state(uid, sub=sub_path)
            sub_path = state.get("sub")
            if not sub_path: # If not, download it
                await status.edit_text("⬇️ Downloading subtitle…", reply_markup=CANCEL_KB)
                sub_path = await download_media(client, state["sub_msg"], status, cancel, "Download", custom_name=f"{out_name}_sub")
                if not sub_path: return
                # Save this subtitle for potential reuse
                sub_token = secrets.token_hex(4)
                SAVED_SUBS[sub_token] = sub_path
                asyncio.create_task(_schedule_file_for_deletion(sub_path, 7200, sub_token, SAVED_SUBS))
                LAST_SUB_TOKENS[uid] = sub_token

            # 3. Download Thumbnail (or use existing)
            if not thumb_path and PERMANENT_THUMBS.get(uid) and os.path.exists(PERMANENT_THUMBS[uid]):
                thumb_path = PERMANENT_THUMBS[uid]
                workflow.set_state(uid, thumb_dl_path=thumb_path)
            thumb_path = state.get("thumb_dl_path")
            if not thumb_path: # If not, download it
                if state.get("thumb_msg"):
                    await status.edit_text("⬇️ Downloading thumbnail…", reply_markup=CANCEL_KB)
                    thumb_path = await download_media(client, state["thumb_msg"], status, cancel, "Download", custom_name=f"{out_name}_thumb")
                    if not thumb_path: return
                    # Save this thumbnail for potential reuse
                    thumb_token = secrets.token_hex(4)
                    SAVED_THUMBS[thumb_token] = thumb_path
                    asyncio.create_task(_schedule_file_for_deletion(thumb_path, 7200, thumb_token, SAVED_THUMBS))
                    LAST_THUMB_TOKENS[uid] = thumb_token

            # 4. Mux
            await status.edit_text("⚙️ Muxing…", reply_markup=CANCEL_KB)
            logger.info(f"User {uid} started muxing {video_path} + {sub_path} -> {out_path}")
            await mux_video(video_path, sub_path, out_path, thumb_path)

            if cancel.is_set():
                return

            # 5. Upload
            caption = extract_caption(out_name + ".mkv")
            await status.edit_text("📤 Uploading…", reply_markup=CANCEL_KB)
            sent_msg = await upload_video(
                client,
                message.chat.id,
                out_path,
                caption=caption,
                thumb=thumb_path,
                status_message=status,
                cancel_flag=cancel,
            )

            if cancel.is_set():
                return

            if not sent_msg:
                base_url = get_base_url()
                if os.path.exists(out_path):
                    out_token = secrets.token_hex(4)
                    SAVED_OUTPUTS[out_token] = out_path
                    asyncio.create_task(_schedule_file_for_deletion(out_path, 7200, out_token, SAVED_OUTPUTS))
                    await client.send_message(
                        message.chat.id,
                        f"⚠️ Upload failed (file might be over 2GB).\nHowever, your muxed video is saved on the server for 2 hours.\n🔗 <b>Download Link:</b> {base_url}/dl/{out_token}",
                        parse_mode=ParseMode.HTML
                    )
                # Upload failed, uploader handled the error message editing.
                # Return here so we don't delete the error message!
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
                base_url = get_base_url()
                reuse_msg = await client.send_message(
                    message.chat.id,
                    f"♻️ Video saved on server for 2 hours!\nTo reuse this video for another mux, use:\n<code>/reuse {token}</code>\n🔗 <b>Download Link:</b> {base_url}/dl/{token}",
                    parse_mode=ParseMode.HTML
                )
                asyncio.create_task(_schedule_msg_for_deletion(reuse_msg, 7200))

            await _delete_status_message(status) # Delete the progress message ONLY ON SUCCESS

        except Exception as e:
            logger.error(f"Mux failed for user {uid}: {e}")
            if not cancel.is_set():
                await status.edit_text(f"❌ Mux failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML)
        finally:
            # Clean up temporary input files that are not saved for reuse (including permanent ones)
            _cleanup_all_temp_for_user(uid)
            # Do NOT aggressively delete the status message here so that errors remain visible!
            workflow.clear_cancel_flag(uid, status.id)
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
        # _cleanup will check if it's a saved file (temp or permanent) and skip if necessary
        _cleanup(p) # Use the _cleanup function that checks against SAVED_ dicts

def _doc_name(message: Message) -> str:
    if message.document:
        return message.document.file_name or ""
    return ""

def _cleanup(*paths):
    for p in paths:
        if p and os.path.exists(p):
            # Check against all saved dictionaries (temporary and permanent)
            if p in SAVED_VIDEOS.values() or p in SAVED_SUBS.values() or p in SAVED_THUMBS.values() or \
               p in PERMANENT_SUBS.values() or p in PERMANENT_THUMBS.values() or p in SAVED_OUTPUTS.values():
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
