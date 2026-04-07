import http.server
import socketserver
import threading
import os
import time
import subprocess
import asyncio
import shutil
import re
import traceback

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIG ---
API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 2115729865
AUTHORIZED_USERS = [ADMIN_ID]

app = Client(
    "FrictionBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=100,
)

user_data: dict = {}
_last_edit: dict[int, float] = {}
_cancelled: set[int] = set()

# --- ASS HEADERS ---
HEADER_CINEMATIC = (
    "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 816\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
    "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
    "-1,0,0,0,70,90,1,0,1,2,2,2,400,400,115,1"
)

HEADER_FULL_4K = (
    "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
    "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
    "-1,0,0,0,70,90,1,0,1,2,2,2,400,400,120,1"
)

CANCEL_BTN = InlineKeyboardMarkup(
    [[InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="stop_all")]]
)


# --- SMART CAPTION ---



# --- CANCELLATION CHECK ---
def _check_cancelled(chat_id: int):
 def generate_friction_caption(filename):
    try:
        clean_name = filename.replace(".mkv", "").replace(".mp4", "")
        quality = "4K" if "4K" in clean_name.upper() else "1080p"
        ep_match = re.search(r"EP(\d+)", clean_name, re.IGNORECASE)
        ep_no = ep_match.group(1) if ep_match else "???"
        name_part = clean_name.split("EP")[0].strip()
        
        # Adding the '>' creates the Blockquote effect in Telegram
        return (
            f"**{name_part}**\n\n"
            f"**Episode :** {ep_no}\n"
            f"**Quality :** {quality}\n"
            f"**Subtitles :** INBUILT"
        )
    except:
        return f"**{filename}**\n\n@TheFrictionRealm"
   if chat_id in _cancelled:
        raise asyncio.CancelledError("Cancelled by user.")


# --- PROGRESS BAR ---
async def progress_bar(current: int, total: int, status_msg, start_time: float, action: str):
    chat_id = status_msg.chat.id

    if chat_id not in user_data or chat_id in _cancelled:
        _cancelled.add(chat_id)
        return

    now = time.time()
    msg_id = status_msg.id
    if current != total and now - _last_edit.get(msg_id, 0) < 4:
        return

    _last_edit[msg_id] = now
    diff = max(now - start_time, 0.001)
    percentage = current * 100 / total
    speed = current / diff
    eta = int((total - current) / speed) if speed > 0 else 0

    def fmt_time(secs: int) -> str:
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    filled = int(10 * current / total)
    bar = "■" * filled + "□" * (10 - filled)

    text = (
        f"**Progress :** `[{bar}]` **{percentage:.1f}%**\n"
        f"**{action} :** `{current/1048576:.1f} MB` | `{total/1048576:.1f} MB`\n"
        f"**Speed :** `{speed/1048576:.2f} MB/s`\n"
        f"**ETA :** `{fmt_time(eta)}`\n"
        f"**Elapsed :** `{fmt_time(int(diff))}`"
    )

    try:
        await status_msg.edit(text, reply_markup=CANCEL_BTN)
    except Exception:
        pass


# --- COMMAND HANDLER ---
@app.on_message(
    filters.command(["style", "convert", "mux"])
    & filters.private
    & filters.user(AUTHORIZED_USERS)
)
async def cmd_handler(client, message):
    mode = message.command[0].lower()
    step = "video" if mode == "mux" else "sub"
    user_data[message.from_user.id] = {"mode": mode, "step": step}
    labels  = {"style": "🎨 Style", "convert": "🔄 Convert", "mux": "📦 Mux"}
    prompts = {
        "style":   "Send your **.srt / .ass** subtitle file.",
        "convert": "Send your **.srt / .ass** subtitle file.",
        "mux":     "Send the **video** file to mux.",
    }
    await message.reply(f"**{labels[mode]} Mode Active.**\n\n{prompts[mode]}")


# --- CALLBACK HANDLER ---
@app.on_callback_query(filters.user(AUTHORIZED_USERS))
async def cb_handler(client, cb):
    chat_id = cb.from_user.id

    if cb.data == "stop_all":
        _cancelled.add(chat_id)
        user_data.pop(chat_id, None)
        _last_edit.clear()
        await cb.message.edit("🛑 **Process Terminated.**")
        await cb.answer()
        return

    if chat_id not in user_data:
        await cb.answer("No active session.", show_alert=True)
        return

    if cb.data.startswith("st_"):
        user_data[chat_id]["header"] = (
            HEADER_CINEMATIC if "cin" in cb.data else HEADER_FULL_4K
        )
        await cb.answer()
        await start_sub_process(client, cb.message, chat_id, "style")

    elif cb.data.startswith("cv_"):
        user_data[chat_id]["ext"] = cb.data.split("_", 1)[1]
        await cb.answer()
        await start_sub_process(client, cb.message, chat_id, "convert")


# --- MAIN MESSAGE HANDLER ---
@app.on_message(
    filters.private
    & ~filters.command(["style", "convert", "mux", "help", "access"])
    & filters.user(AUTHORIZED_USERS)
)
async def main_handler(client, message):
    chat_id = message.from_user.id
    if chat_id not in user_data:
        return

    data = user_data[chat_id]
    mode = data["mode"]
    step = data["step"]

    if mode in ("style", "convert") and step == "sub" and message.document:
        fname = message.document.file_name or "subtitle.srt"
        user_data[chat_id].update({"sub_id": message.id, "orig_sub_name": fname})
        if mode == "style":
            btns = [[
                InlineKeyboardButton("🎞 Cinematic (816p)", callback_data="st_cin"),
                InlineKeyboardButton("📺 Full 4K (1080p)",  callback_data="st_full"),
            ]]
            await message.reply("**Select Style Type:**", reply_markup=InlineKeyboardMarkup(btns))
        else:
            btns = [[
                InlineKeyboardButton("📄 To SRT", callback_data="cv_srt"),
                InlineKeyboardButton("💎 To ASS", callback_data="cv_ass"),
            ]]
            await message.reply("**Select Target Format:**", reply_markup=InlineKeyboardMarkup(btns))
        return

    if mode == "mux":
        if step == "video" and (message.video or message.document):
            user_data[chat_id].update({"vid_id": message.id, "step": "sub"})
            await message.reply("✅ **Video received.** Now send the **.ass** subtitle.")

        elif step == "sub" and message.document:
            user_data[chat_id].update({"sub_id": message.id, "step": "name"})
            await message.reply(
                "✅ **Subtitle received.**\n\n"
                "Type the final output name (without extension):\n"
            )

        elif step == "name" and message.text:
            raw = message.text.strip()
            out_name = raw if raw.lower().endswith(".mkv") else raw + ".mkv"
            user_data[chat_id].update({"out_name": out_name, "step": "thumb"})
            await message.reply(
                "🖼 **Send a thumbnail** (photo) or type `/skip` to proceed without one."
            )

        elif step == "thumb":
            is_skip = message.text and message.text.strip().lower() in ("/skip", "skip")
            if message.photo or is_skip:
                await finalize_mux(client, message, chat_id)


# --- SUB PROCESS (STYLE / CONVERT) ---
async def start_sub_process(client, msg, chat_id: int, task: str):
    work_dir = f"work_sub_{chat_id}_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)
    status = await msg.edit("⏳ **Downloading subtitle...**")

    try:
        _check_cancelled(chat_id)
        data = user_data[chat_id]
        s_msg  = await client.get_messages(chat_id, data["sub_id"])
        s_path = await client.download_media(s_msg, file_name=f"{work_dir}/input.srt")
        _check_cancelled(chat_id)

        base_name = re.sub(r"\.[^.]+$", "", data["orig_sub_name"])
        ext       = "ass" if task == "style" else data["ext"]
        out_path  = os.path.join(work_dir, f"{base_name}.{ext}")

        if task == "style":
            temp_ass = os.path.join(work_dir, "temp.ass")
            result = subprocess.run(
                ["ffmpeg", "-i", s_path, temp_ass, "-y"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg error:\n{result.stderr[-500:]}")

            with open(temp_ass, "r", encoding="utf-8") as f:
                lines = f.readlines()

            events_idx = next(
                (i for i, l in enumerate(lines) if "[Events]" in l), None
            )
            if events_idx is None:
                raise RuntimeError("Could not find [Events] block in converted ASS.")

            with open(out_path, "w", encoding="utf-8") as f:
                f.write(data["header"] + "\n\n" + "".join(lines[events_idx:]))

        else:
            result = subprocess.run(
                ["ffmpeg", "-i", s_path, out_path, "-y"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg error:\n{result.stderr[-500:]}")

        _check_cancelled(chat_id)
        await status.edit("📤 **Uploading result...**")
        await client.send_document(
            chat_id, out_path,
            caption=f"✅ **Done!**\n`{os.path.basename(out_path)}`"
        )

    except asyncio.CancelledError:
        pass
    except Exception as e:
        tb = traceback.format_exc()
        await msg.reply(f"❌ **Error:**\n`{e}`\n\n```\n{tb[-800:]}\n```")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        user_data.pop(chat_id, None)
        _cancelled.discard(chat_id)
        _last_edit.clear()
        try:
            await status.delete()
        except Exception:
            pass


# --- MUX PROCESS ---
async def finalize_mux(client, message, chat_id: int):
    work_dir = f"work_mux_{chat_id}_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)
    status = await message.reply("🚀 **Starting mux pipeline...**")

    try:
        _check_cancelled(chat_id)
        data = user_data[chat_id].copy()

        await status.edit("📥 **Downloading video...**", reply_markup=CANCEL_BTN)
        v_msg    = await client.get_messages(chat_id, data["vid_id"])
        dl_start = time.time()
        v_path   = await client.download_media(
            v_msg,
            file_name=f"{work_dir}/video.mp4",
            progress=progress_bar,
            progress_args=(status, dl_start, "Download"),
        )
        _check_cancelled(chat_id)

        await status.edit("📥 **Downloading subtitle...**")
        s_msg  = await client.get_messages(chat_id, data["sub_id"])
        s_path = await client.download_media(s_msg, file_name=f"{work_dir}/sub.ass")
        _check_cancelled(chat_id)

        thumb_path = None
        if message.photo:
            thumb_path = await client.download_media(
                message.photo, file_name=f"{work_dir}/thumb.jpg"
            )

        out_path = os.path.join(work_dir, data["out_name"])
        caption  = generate_friction_caption(data["out_name"])

        await status.edit(f"⚡ **Muxing:** `{data['out_name']}`")
        result = subprocess.run(
            [
                "ffmpeg", "-i", v_path, "-i", s_path,
                "-map", "0:v:0", "-map", "0:a:0", "-map", "1:s:0",
                "-c:v", "copy", "-c:a", "copy", "-c:s", "ass",
                "-disposition:s:0", "default",
                "-metadata:s:s:0", "title=ENGLISH @TheFrictionRealm",
                out_path, "-y",
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg mux failed:\n{result.stderr[-600:]}")

        _check_cancelled(chat_id)

        await status.edit("📤 **Uploading...**", reply_markup=CANCEL_BTN)
        ul_start = time.time()
        await client.send_document(
            chat_id,
            out_path,
            thumb=thumb_path,
            caption=caption,
            progress=progress_bar,
            progress_args=(status, ul_start, "Upload"),
        )
        _check_cancelled(chat_id)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        tb = traceback.format_exc()
        await message.reply(f"❌ **Error:**\n`{e}`\n\n```\n{tb[-800:]}\n```")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        user_data.pop(chat_id, None)
        _cancelled.discard(chat_id)
        _last_edit.clear()
        try:
            await status.delete()
        except Exception:
            pass


# --- KEEP-ALIVE SERVER ---
def start_server():
    with socketserver.TCPServer(("", 7860), http.server.SimpleHTTPRequestHandler) as httpd:
        httpd.serve_forever()

threading.Thread(target=start_server, daemon=True).start()
app.run()
