import http.server, socketserver, threading, os, time, subprocess, glob, asyncio, shutil, re
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIG ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 2115729865
AUTHORIZED_USERS = [ADMIN_ID]

app = Client("FrictionBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=100)
user_data = {}

# --- HEADERS ---
HEADER_CINEMATIC = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 816\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,70,90,1,0,1,2,2,2,400,400,115,1"
HEADER_FULL_4K = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,70,90,1,0,1,2,2,2,400,400,120,1"

# --- SMART CAPTION ---
def generate_friction_caption(filename):
    try:
        clean_name = filename.replace(".mkv", "").replace(".mp4", "")
        quality = "4K" if "4K" in clean_name.upper() else "1080p"
        ep_match = re.search(r"EP(\d+)", clean_name, re.IGNORECASE)
        ep_no = ep_match.group(1) if ep_match else "???"
        name_part = clean_name.split("EP")[0].strip()
        return (f"**{name_part}**\n\n**EPISODE:** `{ep_no}`\n**QUALITY:** `{quality}`\n**SUBTITLES:** `INBUILT`")
    except: return f"**{filename}**\n\n@TheFrictionRealm"

# --- CORRECTED PROGRESS BAR ---
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
        
        bar = "■" * int(10 * current / total) + "□" * (10 - int(10 * current / total))
        
        # EXACT DESIGN MATCH
        msg = (
            f"**Progress :** `[{bar}]` **{percentage:.1f}%**\n"
            f"**{action} :** `{current/1024/1024:.1f} MB` | `{total/1024/1024:.1f} MB`\n"
            f"**Speed :** `{speed/1024/1024:.2f} MB/s`\n"
            f"**ETA :** `{eta_str}`\n"
            f"**Time elapsed :** `{elapsed_str}`"
        )
        
        try: await status_msg.edit(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="stop_all")]]))
        except: pass

# --- HANDLERS ---
@app.on_message(filters.command(["style", "convert", "mux"]) & filters.private & filters.user(AUTHORIZED_USERS))
async def cmd_handler(client, message):
    mode = message.text.split()[0][1:]
    user_data[message.from_user.id] = {"mode": mode, "step": "video" if mode == "mux" else "sub"}
    await message.reply(f"🚀 **{mode.upper()} Mode Active.**")

@app.on_callback_query()
async def cb_handler(client, cb):
    chat_id = cb.from_user.id
    if cb.data == "stop_all":
        if chat_id in user_data: del user_data[chat_id]
        await cb.message.edit("🛑 **Process Terminated.**")
        return
    if chat_id not in user_data: return
    if cb.data.startswith("st_"):
        user_data[chat_id]["header"] = HEADER_CINEMATIC if "cin" in cb.data else HEADER_FULL_4K
        await start_sub_process(client, cb.message, chat_id, "style")
    elif cb.data.startswith("cv_"):
        user_data[chat_id]["ext"] = cb.data.split("_")[1]
        await start_sub_process(client, cb.message, chat_id, "convert")

@app.on_message(filters.private & ~filters.command(["style", "convert", "mux", "help", "access"]) & filters.user(AUTHORIZED_USERS))
async def main_handler(client, message):
    chat_id = message.from_user.id
    if chat_id not in user_data: return
    data = user_data[chat_id]

    if data["mode"] in ["style", "convert"] and data["step"] == "sub" and message.document:
        user_data[chat_id].update({"sub_id": message.id, "orig_sub_name": message.document.file_name})
        if data["mode"] == "style":
            btns = [[InlineKeyboardButton("🎞 Cinematic", callback_data="st_cin"), InlineKeyboardButton("📺 Full 4K", callback_data="st_full")]]
            await message.reply("Select Style Type:", reply_markup=InlineKeyboardMarkup(btns))
        else:
            btns = [[InlineKeyboardButton("📄 To SRT", callback_data="cv_srt"), InlineKeyboardButton("💎 To ASS", callback_data="cv_ass")]]
            await message.reply("Select Target Format:", reply_markup=InlineKeyboardMarkup(btns))

    elif data["mode"] == "mux":
        if data["step"] == "video" and (message.video or message.document):
            user_data[chat_id].update({"vid_id": message.id, "step": "sub"})
            await message.reply("✅ Video OK. Send Subtitle.")
        elif data["step"] == "sub" and message.document:
            user_data[chat_id].update({"sub_id": message.id, "step": "name"})
            await message.reply("✅ Sub OK. Type Final Name (ex: Shrouding The Heavens EP157 [4K]):")
        elif data["step"] == "name" and message.text:
            user_data[chat_id].update({"out_name": message.text + ".mkv", "step": "thumb"})
            await message.reply("🖼 Send Thumbnail or /skip.")
        elif data["step"] == "thumb" and (message.photo or "/skip" in message.text):
            await finalize_mux(client, message, chat_id)

# --- PROCESS FUNCTIONS ---
async def start_sub_process(client, msg, chat_id, task):
    work_dir = f"work_sub_{chat_id}_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)
    status = await msg.edit("⏳ **Processing...**")
    try:
        data = user_data[chat_id]
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        s_p = await client.download_media(s_msg, file_name=f"{work_dir}/i.srt")
        out = os.path.join(work_dir, f"{data['orig_sub_name'].rsplit('.', 1)[0]}.{'ass' if task == 'style' else data['ext']}")
        if task == "style":
            temp = os.path.join(work_dir, "t.ass")
            subprocess.run(["ffmpeg", "-i", s_p, temp, "-y"], capture_output=True)
            with open(temp, 'r', encoding='utf-8') as f: lines = f.readlines()
            ev = next(i for i, l in enumerate(lines) if "[Events]" in l)
            with open(out, 'w', encoding='utf-8') as f: f.write(data["header"] + "\n\n" + "".join(lines[ev:]))
        else: subprocess.run(["ffmpeg", "-i", s_p, out, "-y"])
        await client.send_document(chat_id, out, caption="✅ Done!")
    except Exception as e: await msg.reply(f"❌ Error: {e}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        if chat_id in user_data: del user_data[chat_id]
        await status.delete()

async def finalize_mux(client, message, chat_id):
    work_dir = f"work_mux_{chat_id}_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)
    status = await message.reply("🚀 **Initializing...**")
    try:
        data = user_data[chat_id].copy()
        v_msg = await client.get_messages(chat_id, data["vid_id"])
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        v_p = await client.download_media(v_msg, file_name=f"{work_dir}/v.mp4", progress=progress_bar, progress_args=(status, time.time(), "Download"))
        s_p = await client.download_media(s_msg, file_name=f"{work_dir}/s.ass")
        th = await client.download_media(message.photo, file_name=f"{work_dir}/t.jpg") if message.photo else None
        out_path = os.path.join(work_dir, data["out_name"])
        cap = generate_friction_caption(data["out_name"])
        await status.edit(f"⚡ **Muxing:** `{data['out_name']}`")
        subprocess.run(["ffmpeg", "-i", v_p, "-i", s_p, "-map", "0:v:0", "-map", "0:a:0", "-map", "1:s:0", "-c:v", "copy", "-c:a", "copy", "-c:s", "ass", "-disposition:s:0", "default", "-metadata:s:s:0", "title=ENGLISH @TheFrictionRealm", out_path, "-y"], check=True)
        await status.edit("📤 **Uploading...**")
        await client.send_document(chat_id, out_path, thumb=th, caption=cap, progress=progress_bar, progress_args=(status, time.time(), "Upload"))
    except Exception as e: await message.reply(f"❌ Error: {e}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        if chat_id in user_data: del user_data[chat_id]
        await status.delete()

def start_server():
    try: socketserver.TCPServer(("", 7860), http.server.SimpleHTTPRequestHandler).serve_forever()
    except: pass
threading.Thread(target=start_server, daemon=True).start()
app.run()
