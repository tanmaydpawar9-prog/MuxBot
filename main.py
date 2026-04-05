import http.server, socketserver, threading, os, time, subprocess, asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply

# --- CONFIG ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Client("FrictionBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_data = {}

# --- FRICTION REALM STYLES ---
STYLE_CINEMATIC = "Arial,24,&H0000FFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1"
STYLE_REGULAR = "Arial,20,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,1,2,10,10,10,1"

# --- IMPROVED PROGRESS BAR (Speed, %, ETA) ---
async def progress_bar(current, total, status_msg, start_time, action):
    now = time.time()
    diff = now - start_time
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        eta = round((total - current) / speed) if speed > 0 else 0
        
        elapsed_str = time.strftime('%M:%S', time.gmtime(round(diff)))
        eta_str = time.strftime('%M:%S', time.gmtime(eta))
        
        blocks = int(percentage / 10)
        bar = "█" * blocks + "░" * (10 - blocks)
        
        msg = (
            f"⚙️ **{action}...**\n\n"
            f"**[{bar}]** {percentage:.1f}%\n"
            f"🚀 Speed: {current/1024/1024/diff:.2f} MB/s\n"
            f"⏳ ETA: {eta_str} | Time: {elapsed_str}"
        )
        try: await status_msg.edit(msg)
        except: pass

# --- COMMANDS ---
@app.on_message(filters.command("style") & filters.private)
async def style_mode(client, message):
    user_data[message.from_user.id] = {"mode": "style"}
    await message.reply("📝 **Sub-Converter Active.**\nSend me the **SRT** or **VTT** file.")

@app.on_message(filters.command("mux") & filters.private)
async def mux_mode(client, message):
    user_data[message.from_user.id] = {"mode": "mux", "step": "video"}
    await message.reply("🎬 **Muxer Active.**\nFirst, send the **Video** file.")

# --- FILE HANDLER ---
@app.on_message((filters.document | filters.video) & filters.private)
async def handle_files(client, message):
    chat_id = message.from_user.id
    if chat_id not in user_data: return
    
    mode = user_data[chat_id].get("mode")

    if mode == "style":
        if message.document and message.document.file_name.lower().endswith((".srt", ".vtt")):
            user_data[chat_id]["sub_id"] = message.id
            btns = [[InlineKeyboardButton("🎬 Cinematic", callback_data="conv_cin"), 
                     InlineKeyboardButton("📝 Regular", callback_data="conv_reg")]]
            await message.reply("Choose Style:", reply_markup=InlineKeyboardMarkup(btns))

    elif mode == "mux":
        step = user_data[chat_id].get("step")
        if step == "video":
            user_data[chat_id]["video_id"] = message.id
            user_data[chat_id]["step"] = "sub"
            await message.reply("✅ Video received. Now send the **Converted .ASS**.")
        elif step == "sub":
            user_data[chat_id]["sub_id"] = message.id
            user_data[chat_id]["step"] = "name"
            await message.reply("✅ Sub received. Type the **Final Name**:", reply_markup=ForceReply(True))

# --- CALLBACKS ---
@app.on_callback_query()
async def convert_sub(client, callback_query):
    chat_id = callback_query.from_user.id
    data = callback_query.data
    if not data.startswith("conv_"): return

    status = await callback_query.message.edit("⏳ Converting...")
    s_msg = await client.get_messages(chat_id, user_data[chat_id]["sub_id"])
    s_path = await client.download_media(s_msg)
    
    out_ass = s_path.rsplit('.', 1)[0] + ".ass"
    style = STYLE_CINEMATIC if "cin" in data else STYLE_REGULAR
    
    # FFmpeg conversion without forcing resolution
    subprocess.run(["ffmpeg", "-i", s_path, "-vf", f"subtitles={s_path}:force_style='{style}'", out_ass, "-y"])
    
    await client.send_document(chat_id, out_ass, caption="✅ Converted! Use /mux now.")
    os.remove(s_path); os.remove(out_ass)
    del user_data[chat_id]

# --- MUXING FINAL ---
@app.on_message(filters.text & filters.reply & filters.private)
async def get_name(client, message):
    chat_id = message.from_user.id
    if user_data.get(chat_id, {}).get("step") == "name":
        user_data[chat_id]["filename"] = message.text + ".mkv"
        user_data[chat_id]["step"] = "thumb"
        await message.reply("🖼 Send **Thumbnail** or /skip.")

@app.on_message((filters.photo | filters.command("skip")) & filters.private)
async def start_muxing(client, message):
    chat_id = message.from_user.id
    if user_data.get(chat_id, {}).get("step") != "thumb": return
    
    status = await message.reply("🚀 Starting Muxer...")
    v_msg = await client.get_messages(chat_id, user_data[chat_id]["video_id"])
    s_msg = await client.get_messages(chat_id, user_data[chat_id]["sub_id"])
    
    v_start = time.time()
    v_path = await client.download_media(v_msg, progress=progress_bar, progress_args=(status, v_start, "Downloading Video"))
    s_path = await client.download_media(s_msg)
    thumb = await client.download_media(message.photo) if message.photo else None
    
    output = user_data[chat_id]["filename"]
    await status.edit("⚡ **Muxing (1:1 Aspect Ratio)...**")
    
    # -c copy -c:s ass ensures NO resolution change!
    subprocess.run(["ffmpeg", "-i", v_path, "-i", s_path, "-map", "0", "-map", "1", "-c", "copy", "-c:s", "ass", output, "-y"])
    
    await status.edit("📤 **Uploading Document...**")
    u_start = time.time()
    # SEND AS DOCUMENT TO KEEP .MKV FORMAT
    await client.send_document(
        chat_id=chat_id, 
        document=output, 
        thumb=thumb, 
        caption=f"**{output}**\n\n@TheFrictionRealm", 
        progress=progress_bar, 
        progress_args=(status, u_start, "Uploading")
    )

    for f in [v_path, s_path, output, thumb]:
        if f and os.path.exists(f): os.remove(f)
    del user_data[chat_id]
    await status.delete()

def start_server():
    socketserver.TCPServer(("", 7860), http.server.SimpleHTTPRequestHandler).serve_forever()

threading.Thread(target=start_server, daemon=True).start()
app.run()
