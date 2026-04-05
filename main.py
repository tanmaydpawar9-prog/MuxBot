import http.server, socketserver, threading, os, time, subprocess
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply

# --- CONFIG ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Client("FrictionBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_data = {}

# --- STYLES ---
STYLE_CINEMATIC = "Arial,24,&H0000FFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1"
STYLE_REGULAR = "Arial,20,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,1,2,10,10,10,1"

# --- PROGRESS BAR ---
async def progress_bar(current, total, status_msg, start_time, action):
    chat_id = status_msg.chat.id
    if chat_id not in user_data:
        raise Exception("STOP_PROCESS")
    now = time.time()
    diff = now - start_time
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        eta = round((total - current) / speed) if speed > 0 else 0
        eta_str = time.strftime('%M:%S', time.gmtime(eta))
        completed = int(15 * current / total)
        bar = "━" * completed + "○" + "─" * (15 - completed)
        icon = "💠" if "Down" in action else "❇️" if "Up" in action else "⚙️"
        msg = (f"{icon} **{action.upper()}**\n"
               f"<code>{bar}</code>  **{percentage:.1f}%**\n\n"
               f"⚡️ `{current/1024/1024/diff:.2f} MB/s`  •  ⏳ `{eta_str}`\n"
               f"📦 `{current/1024/1024:.1f}` / `{total/1024/1024:.1f} MiB`")
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Stop Process", callback_data="stop_all")]])
        try: await status_msg.edit(msg, reply_markup=reply_markup)
        except: pass

# --- COMMANDS & CALLBACKS ---

@app.on_message(filters.command("mux") & filters.private)
async def mux_start(client, message):
    user_data[message.from_user.id] = {"step": "video"}
    await message.reply("🎬 **Friction Realm Muxer Active.**\nSend the **Video** file.")

@app.on_callback_query()
async def handle_callbacks(client, callback_query):
    chat_id = callback_query.from_user.id
    data = callback_query.data
    
    if data == "stop_all":
        if chat_id in user_data:
            del user_data[chat_id]
            await callback_query.message.edit("🛑 **Process Terminated.**\nAll data cleared.")
        return

    if data.startswith("st_"):
        if chat_id not in user_data: return
        user_data[chat_id]["style"] = STYLE_CINEMATIC if "cin" in data else STYLE_REGULAR
        user_data[chat_id]["step"] = "name"
        await callback_query.message.edit("✍️ **Style Set.**\nType the **Final File Name** (Reply to this message):", reply_markup=ForceReply(True))

# --- FILE & TEXT HANDLING ---

@app.on_message(filters.private)
async def main_handler(client, message):
    chat_id = message.from_user.id
    if chat_id not in user_data: return
    step = user_data[chat_id].get("step")

    # Step 1: Video
    if step == "video" and (message.video or message.document):
        user_data[chat_id]["video_id"] = message.id
        user_data[chat_id]["step"] = "sub"
        await message.reply("✅ Video received. Now send the **Subtitle**.")

    # Step 2: Subtitle
    elif step == "sub" and message.document:
        user_data[chat_id]["sub_id"] = message.id
        user_data[chat_id]["step"] = "style_wait"
        btns = [[InlineKeyboardButton("🎬 Cinematic", callback_data="st_cin"), 
                 InlineKeyboardButton("📝 Regular", callback_data="st_reg")]]
        await message.reply("Choose Subtitle Style:", reply_markup=InlineKeyboardMarkup(btns))

    # Step 3: Filename (Reply detection)
    elif step == "name" and message.text:
        user_data[chat_id]["filename"] = message.text + ".mkv"
        user_data[chat_id]["step"] = "thumb"
        await message.reply("🖼 Send **Thumbnail** or /skip.")

    # Step 4: Finalize (Triggered by Photo or /skip)
    elif step == "thumb" and (message.photo or message.text == "/skip"):
        await finalize_process(client, message, chat_id)

async def finalize_process(client, message, chat_id):
    status = await message.reply("🚀 Initializing...")
    v_path = s_path = out_file = thumb_path = None
    try:
        data = user_data[chat_id]
        v_msg = await client.get_messages(chat_id, data["video_id"])
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        
        # Downloads
        v_path = await client.download_media(v_msg, progress=progress_bar, progress_args=(status, time.time(), "Downloading Video"))
        s_path = await client.download_media(s_msg)
        thumb_path = await client.download_media(message.photo) if message.photo else None
        
        # Muxing
        out_file = data["filename"]
        await status.edit("⚡ **Muxing Metadata...**")
        subprocess.run(["ffmpeg", "-i", v_path, "-i", s_path, "-map", "0", "-map", "1", "-c", "copy", "-c:s", "ass", 
                        "-metadata:s:s:0", "title=ENGLISH @TheFrictionRealm", "-metadata:s:s:0", "language=eng", out_file, "-y"])
        
        # Upload
        await status.edit("📤 **Uploading...**")
        await client.send_document(chat_id, out_file, thumb=thumb_path, caption=f"**{out_file}**\n\n@TheFrictionRealm", 
                                   progress=progress_bar, progress_args=(status, time.time(), "Uploading"))

    except Exception as e:
        if str(e) != "STOP_PROCESS": await message.reply(f"❌ Error: {e}")
    
    # Final Cleanup
    for f in [v_path, s_path, out_file, thumb_path]:
        if f and os.path.exists(f): os.remove(f)
    if chat_id in user_data: del user_data[chat_id]
    try: await status.delete()
    except: pass

# --- SERVER ---
def start_server():
    socketserver.TCPServer(("", 7860), http.server.SimpleHTTPRequestHandler).serve_forever()
threading.Thread(target=start_server, daemon=True).start()
app.run()
