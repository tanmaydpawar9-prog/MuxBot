import http.server, socketserver, threading, os, time, subprocess, glob, asyncio, shutil
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIG ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- ACCESS CONTROL ---
ADMIN_ID = 2115729865    # <--- REPLACE WITH YOUR TELEGRAM ID
AUTHORIZED_USERS = [ADMIN_ID] 

app = Client("FrictionBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_data = {}

# --- FRICTION REALM STYLES ---
STYLE_CINEMATIC = "Arial,24,&H0000FFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1"
STYLE_REGULAR = "Arial,20,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,1,2,10,10,10,1"

# --- RENAMEBOT STYLE PROGRESS BAR ---
async def progress_bar(current, total, status_msg, start_time, action):
    chat_id = status_msg.chat.id
    if chat_id not in user_data: raise Exception("STOP_PROCESS")
    now = time.time()
    diff = now - start_time
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        eta = round((total - current) / speed) if speed > 0 else 0
        elapsed_str = f"{int(diff//3600)}h {int((diff%3600)//60)}m {int(diff%60)}s"
        eta_str = f"{int(eta//3600)}h {int((eta%3600)//60)}m {int(eta%60)}s"
        completed = int(10 * current / total)
        bar = "■" * completed + "□" * (10 - completed)
        icon = "📥" if "Down" in action else "📤"
        msg = (f"**Progress:** `[{bar}]` **{percentage:.1f}%**\n"
               f"{icon} **{action}:** `{current/1024/1024:.1f} MB` | `{total/1024/1024:.1f} MB`\n"
               f"⚡️ **Speed:** `{speed/1024/1024:.2f} MB/s`\n"
               f"⏳ **ETA:** `{eta_str}`\n"
               f"⌚️ **Time elapsed:** `{elapsed_str}`")
        try: await status_msg.edit(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="stop_all")]]))
        except: pass

# --- SUBTITLE VALIDATOR ---
def validate_subtitle(file_path):
    errors = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        last_end = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                times = line.split("-->")
                def to_s(t):
                    h, m, s = t.strip().replace(',', '.').split(':')
                    return int(h)*3600 + int(m)*60 + float(s)
                s_s, e_s = to_s(times[0]), to_s(times[1])
                if s_s >= e_s: errors.append(f"L{i+1}: Start >= End")
                if s_s < last_end: errors.append(f"L{i+1}: Overlap detected")
                last_end = e_s
    except: errors.append("Format Error: Not a valid SRT structure")
    return errors

# --- AUTH FILTER ---
def is_auth(_, __, message): return message.from_user.id in AUTHORIZED_USERS
authorized = filters.create(is_auth)

# --- COMMANDS ---
@app.on_message(filters.command(["mux", "style", "convert"]) & filters.private & authorized)
async def cmd_init(client, message):
    mode = message.text.split()[0][1:]
    user_data[message.from_user.id] = {"mode": mode, "step": "video" if mode == "mux" else "sub"}
    await message.reply(f"🚀 **{mode.upper()} Mode Active.** Send the {'Video' if mode == 'mux' else 'Subtitle'} file.")

# --- CALLBACKS ---
@app.on_callback_query()
async def cb_handler(client, cb):
    chat_id = cb.from_user.id
    if cb.data == "stop_all":
        if chat_id in user_data: del user_data[chat_id]
        await cb.message.edit("🛑 **Process Terminated.**")
        return
    if chat_id not in user_data: return
    
    if cb.data.startswith("st_"):
        user_data[chat_id]["style"] = STYLE_CINEMATIC if "cin" in cb.data else STYLE_REGULAR
        await process_sub(client, cb.message, chat_id, "style")
    elif cb.data.startswith("cv_"):
        user_data[chat_id]["ext"] = cb.data.split("_")[1]
        await process_sub(client, cb.message, chat_id, "convert")

# --- MESSAGE HANDLER ---
@app.on_message(filters.private & ~filters.command(["style", "convert", "mux"]) & authorized)
async def main_handler(client, message):
    chat_id = message.from_user.id
    if chat_id not in user_data: return
    data = user_data[chat_id]

    if data["mode"] in ["style", "convert"] and data["step"] == "sub" and message.document:
        user_data[chat_id]["sub_id"] = message.id
        if data["mode"] == "style":
            btns = [[InlineKeyboardButton("🎬 Cinematic", callback_data="st_cin"), InlineKeyboardButton("📝 Regular", callback_data="st_reg")]]
        else:
            btns = [[InlineKeyboardButton("📄 To SRT", callback_data="cv_srt"), InlineKeyboardButton("🌐 To VTT", callback_data="cv_vtt")], [InlineKeyboardButton("💎 To ASS", callback_data="cv_ass")]]
        await message.reply("Select Action:", reply_markup=InlineKeyboardMarkup(btns))

    elif data["mode"] == "mux":
        if data["step"] == "video" and (message.video or message.document):
            user_data[chat_id]["vid_id"], user_data[chat_id]["step"] = message.id, "sub"
            await message.reply("✅ Video OK. Send Subtitle.")
        elif data["step"] == "sub" and message.document:
            user_data[chat_id]["sub_id"], user_data[chat_id]["step"] = message.id, "name"
            await message.reply("✅ Subtitle OK. Type File Name:")
        elif data["step"] == "name" and message.text:
            user_data[chat_id]["out_name"], user_data[chat_id]["step"] = message.text + ".mkv", "thumb"
            await message.reply("🖼 Send Thumbnail or /skip.")
        elif data["step"] == "thumb" and (message.photo or message.text == "/skip"):
            await finalize_mux(client, message, chat_id)

# --- PROCESS STYLE/CONVERT ---
async def process_sub(client, msg, chat_id, task):
    work_dir = f"subwork_{chat_id}_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)
    status = await msg.edit("⏳ **Downloading Subtitle...**")
    
    s_msg = await client.get_messages(chat_id, user_data[chat_id]["sub_id"])
    s_p = await client.download_media(s_msg, file_name=f"{work_dir}/input.srt")
    
    errs = validate_subtitle(s_p)
    if errs:
        await status.edit(f"❌ **Subtitle Error!**\n\n{chr(10).join(errs[:3])}\n\nPlease fix in ASE first.")
        shutil.rmtree(work_dir); return

    out = os.path.join(work_dir, "output" + ("_styled.ass" if task == "style" else f".{user_data[chat_id]['ext']}"))
    if task == "style":
        subprocess.run(["ffmpeg", "-i", s_p, "-vf", f"subtitles={s_p}:force_style='{user_data[chat_id]['style']}'", out, "-y"])
    else:
        subprocess.run(["ffmpeg", "-i", s_p, out, "-y"])
    
    await client.send_document(chat_id, out, caption=f"✅ {task.capitalize()}ed!")
    shutil.rmtree(work_dir)
    del user_data[chat_id]

# --- PROCESS MUXING (MULTI-TASKING ENABLED) ---
async def finalize_mux(client, message, chat_id):
    work_dir = f"muxwork_{chat_id}_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)
    
    status = await message.reply("🚀 **Initializing Multi-Mux...**")
    v_p = s_p = out_path = th = None
    
    try:
        data = user_data[chat_id]
        v_msg = await client.get_messages(chat_id, data["vid_id"])
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        
        v_p = await client.download_media(v_msg, file_name=f"{work_dir}/vid.mp4", progress=progress_bar, progress_args=(status, time.time(), "Downloading"))
        s_p = await client.download_media(s_msg, file_name=f"{work_dir}/sub.ass")
        th = await client.download_media(message.photo, file_name=f"{work_dir}/th.jpg") if message.photo else None
        
        out_name = data["out_name"]
        out_path = os.path.join(work_dir, out_name)

        await status.edit(f"⚡ **Muxing {out_name}...**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="stop_all")]]))
        
        track = "ENGLISH @TheFrictionRealm"
        subprocess.run([
            "ffmpeg", "-i", v_p, "-i", s_p,
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:s:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "ass",
            "-disposition:s:0", "default", "-metadata:s:s:0", f"title={track}",
            "-metadata:s:s:0", "language=eng", out_path, "-y"
        ], check=True)
        
        await status.edit("📤 **Uploading Result...**")
        await client.send_document(chat_id, out_path, thumb=th, caption=f"**{out_name}**\n\n@TheFrictionRealm", progress=progress_bar, progress_args=(status, time.time(), "Uploading"))
    
    except Exception as e:
        if "STOP_PROCESS" not in str(e): await message.reply(f"❌ Error: {e}")
    
    finally:
        if os.path.exists(work_dir): shutil.rmtree(work_dir)
        if chat_id in user_data: del user_data[chat_id]
        try: await status.delete()
        except: pass

# --- SERVER ---
def start_server():
    try: socketserver.TCPServer(("", 7860), http.server.SimpleHTTPRequestHandler).serve_forever()
    except: pass
threading.Thread(target=start_server, daemon=True).start()
app.run()
