import http.server, socketserver, threading, os, time, subprocess
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIG ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Client("FrictionBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_data = {}

# --- FRICTION REALM STYLES ---
STYLE_CINEMATIC = "Arial,24,&H0000FFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1"
STYLE_REGULAR = "Arial,20,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,1,2,10,10,10,1"

# --- NEON PROGRESS BAR ---
async def progress_bar(current, total, status_msg, start_time, action):
    chat_id = status_msg.chat.id
    if chat_id not in user_data: raise Exception("STOP_PROCESS")
    now = time.time()
    diff = now - start_time
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = (current / diff) / (1024 * 1024) if diff > 0 else 0
        eta = round((total - current) / (current / diff)) if current > 0 else 0
        eta_str = time.strftime('%M:%S', time.gmtime(eta))
        bar = "━" * int(15 * current / total) + "○" + "─" * (15 - int(15 * current / total))
        msg = (f"💠 **{action.upper()}**\n<code>{bar}</code> **{percentage:.1f}%**\n\n"
               f"⚡️ `{speed:.2f} MB/s`  •  ⏳ `{eta_str}`")
        try: await status_msg.edit(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Stop", callback_data="stop_all")]]))
        except: pass

# --- COMMAND HANDLERS ---

@app.on_message(filters.command("style") & filters.private)
async def style_init(client, message):
    user_data[message.from_user.id] = {"mode": "style", "step": "sub"}
    await message.reply("🎨 **Styler Mode:** Send the SRT/VTT file to apply Friction Realm styles.")

@app.on_message(filters.command("convert") & filters.private)
async def convert_init(client, message):
    user_data[message.from_user.id] = {"mode": "convert", "step": "sub"}
    await message.reply("🔄 **Converter Mode:** Send any subtitle file to change its format.")

@app.on_message(filters.command("mux") & filters.private)
async def mux_init(client, message):
    user_data[message.from_user.id] = {"mode": "mux", "step": "video"}
    await message.reply("🎬 **Muxer Mode:** Send the **Video** file first.")

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

    # Handle Styling
    if cb.data.startswith("st_"):
        status = await cb.message.edit("⏳ **Applying Styles...**")
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        s_path = await client.download_media(s_msg)
        out_ass = s_path.rsplit('.', 1)[0] + "_styled.ass"
        style = STYLE_CINEMATIC if "cin" in cb.data else STYLE_REGULAR
        subprocess.run(["ffmpeg", "-i", s_path, "-vf", f"subtitles={s_path}:force_style='{style}'", out_ass, "-y"])
        await client.send_document(chat_id, out_ass, caption="✅ **Styled Successfully!**")
        for f in [s_path, out_ass]: 
            if os.path.exists(f): os.remove(f)
        del user_data[chat_id]

    # Handle Conversion
    elif cb.data.startswith("cv_"):
        ext = cb.data.split("_")[1]
        status = await cb.message.edit(f"🔄 **Converting to {ext.upper()}...**")
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        s_path = await client.download_media(s_msg)
        out_file = s_path.rsplit('.', 1)[0] + f".{ext}"
        subprocess.run(["ffmpeg", "-i", s_path, out_file, "-y"])
        await client.send_document(chat_id, out_file, caption=f"✅ **Converted to {ext.upper()}!**")
        for f in [s_path, out_file]: 
            if os.path.exists(f): os.remove(f)
        del user_data[chat_id]

# --- MESSAGE HANDLER ---

@app.on_message(filters.private & ~filters.command(["style", "convert", "mux"]))
async def main_handler(client, message):
    chat_id = message.from_user.id
    if chat_id not in user_data: return
    mode = user_data[chat_id]["mode"]
    step = user_data[chat_id]["step"]

    # SHARED SUBTITLE RECEIVER (for Style & Convert)
    if (mode == "style" or mode == "convert") and step == "sub" and message.document:
        user_data[chat_id]["sub_id"] = message.id
        if mode == "style":
            btns = [[InlineKeyboardButton("🎬 Cinematic (ASS)", callback_data="st_cin"), 
                     InlineKeyboardButton("📝 Regular (ASS)", callback_data="st_reg")]]
            await message.reply("Select Style:", reply_markup=InlineKeyboardMarkup(btns))
        else:
            btns = [[InlineKeyboardButton("📄 To SRT", callback_data="cv_srt"), 
                     InlineKeyboardButton("🌐 To VTT", callback_data="cv_vtt")],
                    [InlineKeyboardButton("💎 To ASS", callback_data="cv_ass")]]
            await message.reply("Select Target Format:", reply_markup=InlineKeyboardMarkup(btns))

    # MUXER LOGIC
    elif mode == "mux":
        if step == "video" and (message.video or message.document):
            user_data[chat_id]["video_id"] = message.id
            user_data[chat_id]["step"] = "sub"
            await message.reply("✅ Video OK. Send the **Subtitle**.")
        elif step == "sub" and message.document:
            user_data[chat_id]["sub_id"] = message.id
            user_data[chat_id]["step"] = "name"
            await message.reply("✅ Subtitle OK. **Type the Final File Name**:")
        elif step == "name" and message.text:
            user_data[chat_id]["filename"] = message.text + ".mkv"
            user_data[chat_id]["step"] = "thumb"
            await message.reply("🖼 Send **Thumbnail** or /skip.")
        elif step == "thumb" and (message.photo or message.text == "/skip"):
            await finalize_mux(client, message, chat_id)

async def finalize_mux(client, message, chat_id):
    status = await message.reply("🚀 **Initializing...**")
    v_path = s_path = out_file = thumb = None
    try:
        data = user_data[chat_id]
        v_msg = await client.get_messages(chat_id, data["video_id"])
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        v_path = await client.download_media(v_msg, progress=progress_bar, progress_args=(status, time.time(), "Downloading Video"))
        s_path = await client.download_media(s_msg)
        thumb = await client.download_media(message.photo) if message.photo else None
        out_file = data["filename"]
        await status.edit("⚡ **Muxing...**")
        # --- THE FIX: SPECIFIC STREAM MAPPING ---
        track_name = "ENGLISH @TheFrictionRealm"
        
        subprocess.run([
            "ffmpeg", "-i", v_path, "-i", s_path,
            "-map", "0:v:0",              # Take ONLY the 4K Video (Stream 0)
            "-map", "0:a:0",              # Take ONLY the Primary Audio (Stream 1)
            "-map", "1:s:0",              # Take ONLY your NEW Synced Subtitle
            "-c:v", "copy",               # Direct Copy Video (No Re-encoding)
            "-c:a", "copy",               # Direct Copy Audio (No Re-encoding)
            "-c:s", "ass",                # Force Subtitle to ASS Format
            "-disposition:s:0", "default", # Make this sub the Default
            "-metadata:s:s:0", f"title={track_name}",
            "-metadata:s:s:0", "language=eng",
            output, "-y"
        ], check=True)
        await status.edit("📤 **Uploading...**")
        await client.send_document(chat_id, out_file, thumb=thumb, caption=f"**{out_file}**\n\n@TheFrictionRealm", 
                                   progress=progress_bar, progress_args=(status, time.time(), "Uploading"))
    except Exception as e:
        if str(e) != "STOP_PROCESS": await message.reply(f"❌ Error: {e}")
    for f in [v_path, s_path, out_file, thumb]:
        if f and os.path.exists(f): os.remove(f)
    if chat_id in user_data: del user_data[chat_id]
    await status.delete()

# --- SERVER ---
def start_server():
    socketserver.TCPServer(("", 7860), http.server.SimpleHTTPRequestHandler).serve_forever()
threading.Thread(target=start_server, daemon=True).start()
app.run()
