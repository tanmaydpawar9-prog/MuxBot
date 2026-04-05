import os
import time
import subprocess
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply

# --- CONFIGURATION ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Client("FrictionBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_data = {}

# --- YOUR CUSTOM STYLES ---
# Replace these strings with the exact styling strings you have.
# Format: Fontname, Fontsize, PrimaryColour, etc.
STYLE_CINEMATIC = "Arial,24,&H0000FFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1"
STYLE_REGULAR = "Arial,20,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,1,2,10,10,10,1"

async def progress_bar(current, total, status_msg, start_time, action):
    now = time.time()
    diff = now - start_time
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        eta = round((total - current) / speed) if speed > 0 else 0
        blocks = int(percentage / 10)
        bar = "█" * blocks + "░" * (10 - blocks)
        msg = (f"⚙️ **{action}...**\n\n**[{bar}]** {percentage:.1f}%\n"
               f"🚀 Speed: {current/1024/1024/diff:.2f} MB/s\n"
               f"⏳ ETA: {time.strftime('%M:%S', time.gmtime(eta))}")
        try: await status_msg.edit(msg)
        except: pass

@app.on_message(filters.video | (filters.document & filters.private))
async def collector(client, message):
    chat_id = message.from_user.id
    # STEP 1: VIDEO
    if message.video or (message.document and "video" in (message.document.mime_type or "")):
        user_data[chat_id] = {"video_id": message.id, "step": "sub"}
        await message.reply("✅ Video received. Now **send the Subtitle (.ass, .srt, .vtt)**.")
    
    # STEP 2: SUBTITLE
    elif message.document and message.document.file_name.lower().endswith((".ass", ".srt", ".vtt")):
        if chat_id in user_data and user_data[chat_id]["step"] == "sub":
            user_data[chat_id]["sub_id"] = message.id
            ext = message.document.file_name.split('.')[-1].lower()
            
            buttons = []
            if ext == "vtt":
                buttons = [[InlineKeyboardButton("Convert to SRT", callback_data="conv_srt"), 
                            InlineKeyboardButton("Convert to ASS", callback_data="conv_ass")]]
            elif ext == "srt":
                buttons = [[InlineKeyboardButton("Convert to VTT", callback_data="conv_vtt"), 
                            InlineKeyboardButton("Convert to ASS", callback_data="conv_ass")]]
            else: # Already .ass
                user_data[chat_id]["target_format"] = "ass"
                user_data[chat_id]["step"] = "name"
                return await message.reply("Subtitle is .ASS. Type the **Final File Name**:", reply_markup=ForceReply(True))
            
            await message.reply(f"Detected {ext.upper()}. Choose target format:", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query()
async def handle_choices(client, callback_query):
    chat_id = callback_query.from_user.id
    data = callback_query.data
    
    if data.startswith("conv_"):
        fmt = data.split("_")[1]
        user_data[chat_id]["target_format"] = fmt
        if fmt == "ass":
            buttons = [[InlineKeyboardButton("🎬 Cinematic", callback_data="style_cinematic"), 
                        InlineKeyboardButton("📝 Regular", callback_data="style_regular")]]
            await callback_query.message.edit("Select **Friction Realm Style**:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            user_data[chat_id]["step"] = "name"
            await callback_query.message.edit(f"Target: {fmt.upper()}. Type the **Final File Name**:", reply_markup=ForceReply(True))

    elif data.startswith("style_"):
        user_data[chat_id]["ass_style"] = STYLE_CINEMATIC if "cinematic" in data else STYLE_REGULAR
        user_data[chat_id]["step"] = "name"
        await callback_query.message.edit("Style set! Type the **Final File Name**:", reply_markup=ForceReply(True))

@app.on_message(filters.text & filters.reply)
async def get_name(client, message):
    chat_id = message.from_user.id
    if chat_id in user_data and user_data[chat_id]["step"] == "name":
        user_data[chat_id]["filename"] = message.text if message.text.endswith(".mkv") else message.text + ".mkv"
        user_data[chat_id]["step"] = "thumb"
        await message.reply("✅ Name set. Send a **Thumbnail (Photo)** or /skip.")

@app.on_message((filters.photo | filters.command("skip")) & filters.private)
async def process_final(client, message):
    chat_id = message.from_user.id
    if chat_id not in user_data or user_data[chat_id]["step"] != "thumb": return
    
    status = await message.reply("🚀 Processing...")
    v_msg = await client.get_messages(chat_id, user_data[chat_id]["video_id"])
    s_msg = await client.get_messages(chat_id, user_data[chat_id]["sub_id"])
    
    # Download
    v_path = await client.download_media(v_msg, progress=progress_bar, progress_args=(status, time.time(), "Downloading Video"))
    s_path = await client.download_media(s_msg)
    thumb_path = await client.download_media(message.photo) if message.photo else None
    
    # Conversion & Styling
    final_sub = s_path.rsplit('.', 1)[0] + ".ass"
    target_fmt = user_data[chat_id].get("target_format", "ass")
    
    if target_fmt == "ass":
        style = user_data[chat_id].get("ass_style", STYLE_REGULAR)
        # Using -vf subtitles to force style during conversion
        subprocess.run(["ffmpeg", "-i", s_path, "-vf", f"subtitles={s_path}:force_style='{style}'", final_sub, "-y"])
    else:
        final_sub = s_path.rsplit('.', 1)[0] + f".{target_fmt}"
        subprocess.run(["ffmpeg", "-i", s_path, final_sub, "-y"])

    # Muxing
    output = user_data[chat_id]["filename"]
    await status.edit("⚡ **Muxing streams...**")
    subprocess.run(["ffmpeg", "-i", v_path, "-i", final_sub, "-map", "0", "-map", "1", "-c", "copy", "-c:s", ass, output, "-y"])

    # Final Upload
    await status.edit("📤 **Uploading Result...**")
    await client.send_video(
        chat_id=chat_id, 
        video=output, 
        thumb=thumb_path, 
        caption=f"**{output}**\n\n@TheFrictionRealm\nJOIN FOR MORE ONGOING CHINESE DONGHUAS", 
        progress=progress_bar, 
        progress_args=(status, time.time(), "Uploading"), 
        supports_streaming=True
    )

    # Cleanup
    for f in [v_path, s_path, final_sub, output, thumb_path]:
        if f and os.path.exists(f): os.remove(f)
    del user_data[chat_id]
    await status.delete()

app.run()
