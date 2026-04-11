import asyncio
import os
import shutil
import threading
import logging
import secrets
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
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Video Token Temp Storage
# ──────────────────────────────────────────────
SAVED_VIDEOS: dict[str, str] = {}

async def delayed_delete(path: str, delay: int = 7200):
    await asyncio.sleep(delay)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
    for k, v in list(SAVED_VIDEOS.items()):
        if v == path:
            del SAVED_VIDEOS[k]

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
    max_concurrent_transmissions=5,
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
        "<b>/style</b> — Style SRT/ASS subtitle\n"
        "<b>/convert</b> — Convert SRT ↔ ASS\n\n"
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
    v = state.get("video_dl_path") or state.get("video")
    s = state.get("sub")
    t = state.get("thumb")
    if v and v not in SAVED_VIDEOS.values(): _cleanup(v)
    _cleanup(s, t)
    
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
    v = state.get("video_dl_path") or state.get("video")
    s = state.get("sub")
    t = state.get("thumb")
    if v and v not in SAVED_VIDEOS.values(): _cleanup(v)
    _cleanup(s, t)
    
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
    workflow.set_state(uid, flow="mux", step="await_video")
    await message.reply(
        "📹 <b>Step 1/4 — Send your video file.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )

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
    workflow.clear_state(uid)
    workflow.set_state(uid, flow="mux", step="await_sub", video_dl_path=SAVED_VIDEOS[token], is_reused=True)
    
    await message.reply(
        "♻️ <b>Video loaded from server!</b>\n\n📄 <b>Step 2/4 — Send your .ass subtitle file.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )

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
    workflow.set_state(uid, flow="style", step="await_sub")
    await message.reply(
        "📄 <b>Step 1/2 — Send your .srt or .ass subtitle file.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )

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
    workflow.set_state(uid, flow="convert", step="await_sub")
    await message.reply(
        "📄 <b>Send your .srt or .ass file to convert.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )

# ──────────────────────────────────────────────
# /skip  (thumbnail skip in mux flow)
# ──────────────────────────────────────────────
@app.on_message(filters.command("skip"))
@auth_only
async def cmd_skip(client, message: Message):
    uid = message.from_user.id
    state = workflow.get_state(uid)
    if state.get("flow") == "mux" and state.get("step") == "await_thumb":
        workflow.set_state(uid, thumb_msg=None, step="await_filename")
        await message.reply(
            "✏️ <b>Step 4/4 — Send the output filename</b> (without extension):",
            parse_mode=ParseMode.HTML,
            reply_markup=CANCEL_KB,
        )
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
        await cq.message.edit_text(
            "✏️ <b>Step 4/4 — Send the output filename</b> (without extension):",
            parse_mode=ParseMode.HTML,
            reply_markup=CANCEL_KB,
        )
    else:
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
        
        await cq.message.edit_text("⬇️ Downloading video…", reply_markup=CANCEL_KB)
        path = await download_media(client, video_msg, cq.message, cancel, "Download")
        if not path:
            return
            
        workflow.set_state(uid, video_dl_path=path)
        
        await cq.message.edit_text(
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
    workflow.set_state(uid, mode=mode, step="processing")
    await cq.message.edit_text(f"⚙️ Applying <b>{'Cinematic 816p' if mode == 'cinematic' else 'Full 4K 1080p'}</b> style…", parse_mode=ParseMode.HTML)

    sub_path = state["sub"]
    out_path = sub_path.rsplit(".", 1)[0] + f"_{mode}.ass"
    cancel = workflow.get_cancel_flag(uid)

    logger.info(f"User {uid} applying style {mode} to {sub_path}")
    try:
        await inject_style(sub_path, out_path, mode)
    except Exception as e:
        logger.error(f"Style failed: {e}")
        await cq.message.edit_text(f"❌ Failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML)
        _cleanup(sub_path)
        workflow.clear_state(uid)
        return

    if cancel.is_set():
        _cleanup(sub_path, out_path)
        workflow.clear_state(uid)
        return

    await client.send_document(
        cq.message.chat.id,
        out_path,
        caption=f"✅ Styled subtitle ({mode})",
        reply_to_message_id=state.get("origin_msg_id"),
    )
    _cleanup(sub_path, out_path)
    workflow.clear_state(uid)

# ──────────────────────────────────────────────
# Convert direction callback
# ──────────────────────────────────────────────
@app.on_callback_query(filters.regex("^conv_(srt2ass|ass2srt)$"))
@auth_only
async def cb_convert_dir(client, cq: CallbackQuery):
    uid = cq.from_user.id
    state = workflow.get_state(uid)
    if state.get("flow") != "convert" or state.get("step") != "await_dir":
        await cq.answer("Not in convert flow.", show_alert=True)
        return

    direction = cq.data.split("_", 1)[1]
    sub_path = state["sub"]
    ext_in = os.path.splitext(sub_path)[1].lower()

    # Validate direction matches file
    if direction == "srt2ass" and ext_in != ".srt":
        await cq.answer("File is not .srt", show_alert=True)
        return
    if direction == "ass2srt" and ext_in != ".ass":
        await cq.answer("File is not .ass", show_alert=True)
        return

    out_ext = ".ass" if direction == "srt2ass" else ".srt"
    out_path = sub_path.rsplit(".", 1)[0] + "_converted" + out_ext
    await cq.message.edit_text("⚙️ Converting…")

    logger.info(f"User {uid} converting {sub_path} direction {direction}")
    try:
        await convert_subtitle(sub_path, out_path)
    except Exception as e:
        logger.error(f"Conversion failed: {e}")
        await cq.message.edit_text(f"❌ Failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML)
        _cleanup(sub_path)
        workflow.clear_state(uid)
        return

    await client.send_document(
        cq.message.chat.id,
        out_path,
        caption=f"✅ Converted: {os.path.basename(out_path)}",
        reply_to_message_id=state.get("origin_msg_id"),
    )
    _cleanup(sub_path, out_path)
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

    cancel = workflow.get_cancel_flag(uid)
    if cancel.is_set():
        return

    # ── MUX FLOW ──────────────────────────────
    if flow == "mux":

        if step == "await_video":
            if not (message.video or (message.document and message.document.mime_type and "video" in message.document.mime_type)):
                await message.reply("⚠️ Please send a video file.")
                return
            workflow.set_state(uid, video_msg=message, step="await_sub", is_reused=False)
            await message.reply(
                "📄 <b>Step 2/4 — Send your .ass subtitle file.</b>\n"
                "<i>(Files will download at the end, or click below to download the video now)</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬇️ Download Video Now", callback_data="dl_video_first")],
                    [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")]
                ])
            )

        elif step == "await_sub":
            fname = _doc_name(message)
            if not fname.endswith(".ass"):
                await message.reply("⚠️ Please send an .ass subtitle file.")
                return
            workflow.set_state(uid, sub_msg=message, step="await_thumb")
            await message.reply(
                "🖼 <b>Step 3/4 — Send a thumbnail image or skip.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏭ Skip Thumbnail", callback_data="skip_thumb")],
                    [InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel")]
                ]),
            )

        elif step == "await_thumb":
            workflow.set_state(uid, thumb_msg=message, step="await_filename")
            await message.reply(
                "✏️ <b>Step 4/4 — Send the output filename</b> (without extension):",
                parse_mode=ParseMode.HTML,
                reply_markup=CANCEL_KB,
            )

    # ── STYLE FLOW ────────────────────────────
    elif flow == "style":
        if step == "await_sub":
            fname = _doc_name(message)
            if not (fname.endswith(".srt") or fname.endswith(".ass")):
                await message.reply("⚠️ Please send a .srt or .ass file.")
                return
            status = await message.reply("⬇️ Downloading subtitle…", reply_markup=CANCEL_KB)
            path = await download_media(client, message, status, cancel, "Download")
            if not path:
                workflow.clear_state(uid); return
            workflow.set_state(uid, sub=path, step="await_mode", origin_msg_id=message.id)
            await status.edit_text(
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
        if step == "await_sub":
            fname = _doc_name(message)
            if not (fname.endswith(".srt") or fname.endswith(".ass")):
                await message.reply("⚠️ Please send a .srt or .ass file.")
                return
            status = await message.reply("⬇️ Downloading subtitle…", reply_markup=CANCEL_KB)
            path = await download_media(client, message, status, cancel, "Download")
            if not path:
                workflow.clear_state(uid); return

            ext = os.path.splitext(fname)[1].lower()
            # Auto-detect direction
            workflow.set_state(uid, sub=path, step="await_dir", origin_msg_id=message.id)
            buttons = []
            if ext == ".srt":
                buttons.append(InlineKeyboardButton("SRT → ASS", callback_data="conv_srt2ass"))
            else:
                buttons.append(InlineKeyboardButton("ASS → SRT", callback_data="conv_ass2srt"))
            buttons.append(InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="cancel"))

            await status.edit_text(
                "🔄 <b>Choose conversion direction:</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([buttons]),
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
        if not out_name:
            await message.reply("⚠️ Please send a valid filename.")
            return

        cancel = workflow.get_cancel_flag(uid)
        is_reused = state.get("is_reused", False)
        video_path = state.get("video_dl_path")
        sub_path = None
        thumb_path = None
        out_path = f"downloads/{out_name}.mkv"

        status = await message.reply("⚙️ Preparing…", reply_markup=CANCEL_KB)

        try:
            # 1. Download Video
            if not video_path:
                if is_reused:
                    await status.edit_text("❌ Error: Reused video path missing.")
                    return
                await status.edit_text("⬇️ Downloading video…", reply_markup=CANCEL_KB)
                video_path = await download_media(client, state["video_msg"], status, cancel, "Download")
                if not video_path:
                    return
                workflow.set_state(uid, video_dl_path=video_path)

            # 2. Download Subtitle
            await status.edit_text("⬇️ Downloading subtitle…", reply_markup=CANCEL_KB)
            sub_path = await download_media(client, state["sub_msg"], status, cancel, "Download")
            if not sub_path:
                return

            # 3. Download Thumbnail
            if state.get("thumb_msg"):
                await status.edit_text("⬇️ Downloading thumbnail…", reply_markup=CANCEL_KB)
                thumb_path = await download_media(client, state["thumb_msg"], status, cancel, "Download")
                if cancel.is_set():
                    return

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
                caption=caption,
                thumb=thumb_path,
                status_msg=status,
                cancel_flag=cancel,
            )

            if cancel.is_set():
                return

            # Token logic
            if not is_reused:
                token = secrets.token_hex(4)
                _, ext = os.path.splitext(video_path)
                saved_video_path = f"downloads/saved_{token}{ext}"
                try:
                    os.rename(video_path, saved_video_path)
                    SAVED_VIDEOS[token] = saved_video_path
                    asyncio.create_task(delayed_delete(saved_video_path, 7200))
                    video_path = saved_video_path
                except Exception:
                    token = None
                    _cleanup(video_path)
            else:
                token = next((k for k, v in SAVED_VIDEOS.items() if v == video_path), None)
            
            if token:
                await client.send_message(
                    message.chat.id,
                    f"♻️ Video saved on server for 2 hours!\nTo reuse this video for another mux, use:\n<code>/reuse {token}</code>",
                    parse_mode=ParseMode.HTML
                )

        except Exception as e:
            logger.error(f"Mux failed: {e}")
            if not cancel.is_set():
                await status.edit_text(f"❌ Mux failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML)
        finally:
            _cleanup(sub_path, thumb_path, out_path)
            if cancel.is_set() or (not is_reused and video_path and video_path not in SAVED_VIDEOS.values()):
                _cleanup(video_path)
            workflow.clear_state(uid)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
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


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    _start_keepalive()
    logger.info("🚀 MuxBot starting…")
    app.run()
