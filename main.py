import http.server, socketserver, threading, os, time, subprocess, shutil, re, traceback, asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIG ---
API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 2115729865
AUTHORIZED_USERS = [ADMIN_ID]

app = Client("FrictionBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=100)

user_data: dict = {}
_last_edit: dict[int, float] = {}
_cancelled: set[int] = set()

# --- 1. HEADERS & SMART CAPTION ---
HEADER_CINEMATIC = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 816\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,70,90,1,0,1,2,2,2,400,400,115,1"
HEADER_FULL_4K = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,70,90,1,0,1,2,2,2,400,400,120,1"

def generate_friction_caption(filename: str) -> str:
    try:
        clean = re.sub(r"\.(mkv|mp4)$", "", filename, flags=re.IGNORECASE)
        ep_match = re.search(r"EP\s*(\d+)", clean, re.IGNORECASE)
        ep_no = ep_match.group(1) if ep_match else "???"
        q_match = re.search(r"\b(4K|2K|1080p|720p)\b", clean, re.IGNORECASE)
        quality = q_match.group(1).upper() if q_match else "4K"
        name_part = re.split(r"EP\s*\d+", clean, flags=re.IGNORECASE)[0]
        name_part = re.sub(r"[\[\(][^\]\)]*[\]\)]", "", name_part).strip(" -_").title()
        
        return (f"**{name_part}**\n\n"
                f"> **EPISODE {ep_no}**\n"
                f"> **QUALITY : {quality}**\n"
                f"> **SUBTITLE : INBUILT**")
    except: return f"**{filename}**\n\n@TheFrictionRealm"

# --- 2. PROGRESS BAR ---
async def progress_bar(current: int, total: int, status_msg, start_time: float, action: str):
    chat_id = status_msg.chat.id
    if chat_id in _cancelled: raise Exception("STOP_PROCESS")
    now = time.time()
    if current != total and now - _last_edit.get(status_msg.id, 0) < 4: return
    _last_edit[status_msg.id] = now
    diff = max(now - start_time, 0.001)
    percentage = current * 100 / total
    speed = current / diff
    eta = int((total - current) / speed) if speed > 0 else 0
    def fmt_time(secs: int):
        h, rem = divmod(secs, 3600); m, s = divmod(rem, 60)
        return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
    bar = "■" * int(10 * current / total) + "□" * (10 - int(10 * current / total))
    text = (f"**Progress :** `[{bar}]` **{percentage:.1f}%**\n"
            f"**{action} :** `{current/1048576:.1f} MB` | `{total/1048576:.1f} MB`\n"
            f"**Speed :** `{speed/1048576:.2f} MB/s`\n"
            f"**ETA :** `{fmt_time(eta)}`\n"
            f"**Time elapsed :** `{fmt_time(int(diff))}`")
    try: await status_msg.edit(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="stop_all")]]))
    except: pass

# --- 3. PROCESSING CORE ---
async def finalize_mux(client, message, chat_id: int, data: dict):
    work_dir = f"work_mux_{chat_id}_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)
    
    # Clean Chat: Delete only bot prompts and initial command
    if "msg_ids" in data: asyncio.create_task(client.delete_messages(chat_id, data["msg_ids"]))
        
    status = await client.send_message(chat_id, "🚀 **Initializing Mux Pipeline...**")
    try:
        v_msg = await client.get_messages(chat_id, data["vid_id"])
        v_path = await client.download_media(v_msg, file_name=f"{work_dir}/v.mp4", progress=progress_bar, progress_args=(status, time.time(), "Download"))
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        s_path = await client.download_media(s_msg, file_name=f"{work_dir}/s.ass")
        th = await client.download_media(message.photo, file_name=f"{work_dir}/t.jpg") if message.photo else None
        out = os.path.join(work_dir, data["out_name"])
        await status.edit(f"⚡ **Muxing...**")
        subprocess.run(["ffmpeg", "-i", v_path, "-i", s_path, "-map", "0:v:0", "-map", "0:a:0", "-map", "1:s:0", "-c:v", "copy", "-c:a", "copy", "-c:s", "ass", "-metadata:s:s:0", "title=ENGLISH @TheFrictionRealm", out, "-y"], check=True)
        await status.edit("📤 **Uploading...**")
        await client.send_document(chat_id, out, thumb=th, caption=generate_friction_caption(data["out_name"]), progress=progress_bar, progress_args=(status, time.time(), "Upload"))
    except Exception as e: 
        if "STOP_PROCESS" in str(e): await status.edit("🛑 **Process Cancelled.**")
        else: await client.send_message(chat_id, f"❌ Error: {e}")
    finally: shutil.rmtree(work_dir, ignore_errors=True); _cancelled.discard(chat_id); await status.delete()

async def start_sub_process(client, msg, chat_id: int, task: str, data: dict):
    work_dir = f"work_sub_{chat_id}_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)
    
    if "msg_ids" in data: asyncio.create_task(client.delete_messages(chat_id, data["msg_ids"]))
        
    status = await client.send_message(chat_id, "⏳ **Processing Subtitle...**")
    try:
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        s_p = await client.download_media(s_msg, file_name=f"{work_dir}/i.srt")
        out = os.path.join(work_dir, f"{data['orig_sub_name'].rsplit('.', 1)[0]}.{'ass' if task == 'style' else data['ext']}")
        if task == "style":
            temp = os.path.join(work_dir, "t.ass")
            subprocess.run(["ffmpeg", "-i", s_p, temp, "-y"])
            with open(temp, "r", encoding="utf-8") as f: lines = f.readlines()
            ev = next(i for i, l in enumerate(lines) if "[Events]" in l)
            with open(out, "w", encoding="utf-8") as f: f.write(data["header"] + "\n\n" + "".join(lines[ev:]))
        else: subprocess.run(["ffmpeg", "-i", s_p, out, "-y"])
        await client.send_document(chat_id, out, caption="✅ **Subtitle Ready!**")
    except Exception as e: await client.send_message(chat_id, f"❌ Error: {e}")
    finally: shutil.rmtree(work_dir, ignore_errors=True); await status.delete()

# --- 4. HANDLERS ---
@app.on_message(filters.command(["style", "convert", "mux", "speed"]) & filters.private & filters.user(AUTHORIZED_USERS))
async def cmd_handler(client, message):
    mode = message.command[0].lower()
    
    if mode == "speed":
        import speedtest
        m = await message.reply("🚀 Testing Speed...")
        loop = asyncio.get_running_loop()
        st = await loop.run_in_executor(None, speedtest.Speedtest)
        await loop.run_in_executor(None, st.get_best_server)
        dl = await loop.run_in_executor(None, st.download)
        ul = await loop.run_in_executor(None, st.upload)
        await m.edit(f"📊 **HF Speed:**\n📥 DL: `{dl/1048576:.2f} MB/s` | 📤 UL: `{ul/1048576:.2f} MB/s`")
        return

    # Track the user's initial command (/mux) so it gets deleted
    user_data[message.from_user.id] = {"mode": mode, "step": "video" if mode == "mux" else "sub", "msg_ids": [message.id]}
    
    if mode == "mux":
        m = await message.reply("📦 **Mux Mode Active.**\n\nSend the video file to mux.")
    else:
        m = await message.reply(f"🎨 **{mode.title()} Mode Active.**\n\nSend the .srt/.ass subtitle file.")
        
    user_data[message.from_user.id]["msg_ids"].append(m.id)

@app.on_callback_query(filters.user(AUTHORIZED_USERS))
async def cb_handler(client, cb):
    chat_id = cb.from_user.id
    if cb.data == "stop_all":
        _cancelled.add(chat_id); user_data.pop(chat_id, None); await cb.message.edit("🛑 Terminated."); return
        
    data = user_data.pop(chat_id, None)
    if not data: return
    
    # Add the button menu to deletion list
    if "msg_ids" in data: data["msg_ids"].append(cb.message.id)
        
    if cb.data.startswith("st_"):
        data["header"] = HEADER_CINEMATIC if "cin" in cb.data else HEADER_FULL_4K
        asyncio.create_task(start_sub_process(client, cb.message, chat_id, "style", data))
    elif cb.data.startswith("cv_"):
        data["ext"] = cb.data.split("_")[1]
        asyncio.create_task(start_sub_process(client, cb.message, chat_id, "convert", data))

@app.on_message(filters.private & ~filters.command(["style", "convert", "mux", "speed"]) & filters.user(AUTHORIZED_USERS))
async def main_handler(client, message):
    chat_id = message.from_user.id
    if chat_id not in user_data: return
    data = user_data[chat_id]
    
    # NOTE: We are NO LONGER tracking `message.id` here, so the user's files and text are kept.
    
    if data["mode"] in ("style", "convert") and data["step"] == "sub" and message.document:
        data.update({"sub_id": message.id, "orig_sub_name": message.document.file_name})
        btns = [[InlineKeyboardButton("🎞 Cinematic", callback_data="st_cin"), InlineKeyboardButton("📺 Full 4K", callback_data="st_full")]] if data["mode"] == "style" else [[InlineKeyboardButton("📄 To SRT", callback_data="cv_srt"), InlineKeyboardButton("💎 To ASS", callback_data="cv_ass")]]
        m = await message.reply("Select Subtype:", reply_markup=InlineKeyboardMarkup(btns))
        data["msg_ids"].append(m.id)
        
    elif data["mode"] == "mux":
        if data["step"] == "video" and (message.video or message.document):
            data.update({"vid_id": message.id, "step": "sub"})
            m = await message.reply("✅ Video received. Now send the .ass subtitle.")
            data["msg_ids"].append(m.id)
            
        elif data["step"] == "sub" and message.document:
            data.update({"sub_id": message.id, "step": "name"})
            m = await message.reply("✅ Subtitle received.\n\nType the final output name (without extension):")
            data["msg_ids"].append(m.id)
            
        elif data["step"] == "name" and message.text:
            data.update({"out_name": message.text + ".mkv", "step": "thumb"})
            m = await message.reply("🖼 Send a thumbnail (photo) or type `/skip` to proceed without one.")
            data["msg_ids"].append(m.id)
            
        elif data["step"] == "thumb":
            if message.photo or (message.text and "/skip" in message.text):
                task_data = user_data.pop(chat_id)
                asyncio.create_task(finalize_mux(client, message, chat_id, task_data))

def start_server():
    socketserver.TCPServer(("", 7860), http.server.SimpleHTTPRequestHandler).serve_forever()
threading.Thread(target=start_server, daemon=True).start()
app.run()
