import http.server, socketserver, threading, os, time, subprocess, glob
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIG ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- ACCESS CONTROL ---
ADMIN_ID = 2115729865  # <--- REPLACE WITH YOUR ID
AUTHORIZED_USERS = [ADMIN_ID] # Add subscriber IDs here

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
        
        # Segmented Bar: ■■■□□□□□□□
        completed = int(10 * current / total)
        bar = "■" * completed + "□" * (10 - completed)
        
        icon = "📥" if "Down" in action else "📤"
        msg = (
            f"**Progress:** `[{bar}]` **{percentage:.1f}%**\n"
            f"{icon} **{action}:** `{current/1024/1024:.1f} MB` | `{total/1024/1024:.1f} MB`\n"
            f"⚡️ **Speed:** `{speed/1024/1024:.2f} MB/s`\n"
            f"⏳ **ETA:** `{eta_str}`\n"
            f"⌚️ **Time elapsed:** `{elapsed_str}`"
        )
        try: await status_msg.edit(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="stop_all")]]))
        except: pass

# --- AUTH FILTER ---
def is_auth(_, __, message):
    return message.from_user.id in AUTHORIZED_USERS
authorized = filters.create(is_auth)

# --- COMMAND HANDLERS ---
@app.on_message(filters.command("style") & filters.private & authorized)
async def style_init(client, message):
    user_data[message.from_user.id] = {"mode": "style", "step": "sub"}
    await message.reply("🎨 **Styler Mode:** Send the SRT/VTT file.")

@app.on_message(filters.command("convert") & filters.private & authorized)
async def convert_init(client, message):
    user_data[message.from_user.id] = {"mode": "convert", "step": "sub"}
    await message.reply("🔄 **Converter Mode:** Send any subtitle file.")

@app.on_message(filters.command("mux") & filters.private & authorized)
async def mux_init(client, message):
    user_data[message.from_user.id] = {"mode": "mux", "step": "video"}
    await message.reply("🎬 **Muxer Mode:** Send the **Video** file.")

# --- CALLBACK HANDLER ---
@app.on_callback_query()
async def cb_handler(client, cb):
    chat_id = cb.from_user.id
    if cb.data == "stop_all":
        if chat_id in user_data: del user_data[chat_id]
        await cb.message.edit("🛑 **Process Terminated.**")
        return

    if chat_id not in user_data: return
    data = user_data[chat_id]

    if cb.data.startswith("st_"):
        status = await cb.message.edit("⏳ **Applying Styles...**")
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        s_path = await client.download_media(s_msg)
        out_ass = s_path.rsplit('.', 1)[0] + "_styled.ass"
        style = STYLE_CINEMATIC if "cin" in cb.data else STYLE_REGULAR
        subprocess.run(["ffmpeg", "-i", s_path, "-vf", f"subtitles={s_path}:force_style='{style}'", out_ass, "-y"])
        await client.send_document(chat_id, out_ass, caption="✅ **Styled Successfully!**")
        for f in [s_path, out_ass]: 
            if f and os.path.exists(f): os.remove(f)
        del user_data[chat_id]

    elif cb.data.startswith("cv_"):
        ext = cb.data.split("_")[1]
        status = await cb.message.edit(f"🔄 **Converting to {ext.upper()}...**")
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        s_path = await client.download_media(s_msg)
        out_file = s_path.rsplit('.', 1)[0] + f".{ext}"
        subprocess.run(["ffmpeg", "-i", s_path, out_file, "-y"])
        await client.send_document(chat_id, out_file, caption=f"✅ **Converted to {ext.upper()}!**")
        for f in [s_path, out_file]: 
            if f and os.path.exists(f): os.remove(f)
        del user_data[chat_id]

# --- MESSAGE HANDLER ---
@app.on_message(filters.private & ~filters.command(["style", "convert", "mux"]) & authorized)
async def main_handler(client, message):
    chat_id = message.from_user.id
    if chat_id not in user_data: return
    mode, step = user_data[chat_id]["mode"], user_data[chat_id]["step"]

    if (mode == "style" or mode == "convert") and step == "sub" and message.document:
        user_data[chat_id]["sub_id"] = message.id
        if mode == "style":
            btns = [[InlineKeyboardButton("🎬 Cinematic", callback_data="st_cin"), InlineKeyboardButton("📝 Regular", callback_data="st_reg")]]
            await message.reply("Select Style:", reply_markup=InlineKeyboardMarkup(btns))
        else:
            btns = [[InlineKeyboardButton("📄 To SRT", callback_data="cv_srt"), InlineKeyboardButton("🌐 To VTT", callback_data="cv_vtt")], [InlineKeyboardButton("💎 To ASS", callback_data="cv_ass")]]
            await message.reply("Select Format:", reply_markup=InlineKeyboardMarkup(btns))

    elif mode == "mux":
        if step == "video" and (message.video or message.document):
            user_data[chat_id]["video_id"], user_data[chat_id]["step"] = message.id, "sub"
            await message.reply("✅ Video OK. Send Subtitle.")
        elif step == "sub" and message.document:
            user_data[chat_id]["sub_id"], user_data[chat_id]["step"] = message.id, "name"
            await message.reply("✅ Subtitle OK. Type File Name:")
        elif step == "name" and message.text:
            user_data[chat_id]["out_name"], user_data[chat_id]["step"] = message.text + ".mkv", "thumb"
            await message.reply("🖼 Send Thumbnail or /skip.")
        elif step == "thumb" and (message.photo or message.text == "/skip"):
            await finalize_mux(client, message, chat_id)

async def finalize_mux(client, message, chat_id):
    # Deep Clean Workspace
    for file in glob.glob("*.*"):
        if file.endswith((".mkv", ".mp4", ".ass", ".srt", ".jpg")):
            try: os.remove(file)
            except: pass
            
    status = await message.reply("🚀 **Initializing...**")
    v_p = s_p = out = th = None
    try:
        data = user_data[chat_id]
        v_msg = await client.get_messages(chat_id, data["video_id"])
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        
        v_p = await client.download_media(v_msg, progress=progress_bar, progress_args=(status, time.time(), "Downloading"))
        s_p = await client.download_media(s_msg)
        th = await client.download_media(message.photo) if message.photo else None
        out = data["out_name"]
        
        await status.edit("⚡ **Muxing...**")
        track = "ENGLISH @TheFrictionRealm"
        
        subprocess.run([
            "ffmpeg", "-i", v_p, "-i", s_p,
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:s:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "ass",
            "-disposition:s:0", "default", "-metadata:s:s:0", f"title={track}",
            "-metadata:s:s:0", "language=eng", out, "-y"
        ], check=True)
        
        if not os.path.exists(out) or os.path.getsize(out) < 1000: raise Exception("FFmpeg failed to create file.")
        
        await status.edit("📤 **Uploading...**")
        await client.send_document(chat_id, out, thumb=th, caption=f"**{out}**\n\n@TheFrictionRealm", progress=progress_bar, progress_args=(status, time.time(), "Uploading"))
    except Exception as e:
        if str(e) != "STOP_PROCESS": await message.reply(f"❌ Error: {e}")
    
    for f in [v_p, s_p, out, th]:
        if f and os.path.exists(f): os.remove(f)
    if chat_id in user_data: del user_data[chat_id]
    try: await status.delete()
    except: pass

def start_server():
    socketserver.TCPServer(("", 7860), http.server.SimpleHTTPRequestHandler).serve_forever()
threading.Thread(target=start_server, daemon=True).start()
app.run()
