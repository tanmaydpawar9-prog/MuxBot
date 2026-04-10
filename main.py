import http.server, socketserver, threading, os, time, subprocess, shutil, re, traceback, asyncio, hashlib, json
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIG ---
API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")   # e.g. https://frictionx7-frictionbot.hf.space

ADMIN_ID = 2115729865
AUTHORIZED_USERS = [ADMIN_ID]

# --- CACHE CONFIG ---
CACHE_DIR   = os.path.join(os.path.expanduser("~"), "app", "cache")
LEECH_DIR   = os.path.join(os.path.expanduser("~"), "app", "leech")
CACHE_TTL   = 2 * 3600   # 2 hours in seconds
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(LEECH_DIR, exist_ok=True)

SIZE_2GB = 2 * 1024 * 1024 * 1024   # 2 GB in bytes

app = Client("FrictionBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=100)

user_data: dict = {}
_last_edit: dict[int, float] = {}
_cancelled: set[int] = set()

# --- 1. HEADERS & SMART CAPTION ---
HEADER_CINEMATIC = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 816\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,70,90,1,0,1,2,2,2,400,400,115,1"
HEADER_FULL_4K   = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,70,90,1,0,1,2,2,2,400,400,120,1"


def generate_friction_caption(filename: str) -> str:
    try:
        clean    = re.sub(r"\.(mkv|mp4)$", "", filename, flags=re.IGNORECASE)
        ep_match = re.search(r"EP\s*(\d+)", clean, re.IGNORECASE)
        ep_no    = ep_match.group(1) if ep_match else "???"
        q_match  = re.search(r"\b(4K|2K|1080p|720p)\b", clean, re.IGNORECASE)
        quality  = q_match.group(1).upper() if q_match else "4K"
        name_part = re.split(r"EP\s*\d+", clean, flags=re.IGNORECASE)[0]
        name_part = re.sub(r"[\[\(][^\]\)]*[\]\)]", "", name_part).strip(" -_").title()
        return (f"**{name_part}**\n\n"
                f"> **EPISODE {ep_no}**\n"
                f"> **QUALITY : {quality}**\n"
                f"> **SUBTITLE : INBUILT**")
    except:
        return f"**{filename}**\n\n@TheFrictionRealm"


# ─────────────────────────────────────────────
# 2. VIDEO CACHE  (keyed by Telegram file_id)
# ─────────────────────────────────────────────
def _cache_key(file_id: str) -> str:
    return hashlib.md5(file_id.encode()).hexdigest()

def _cache_index_path() -> str:
    return os.path.join(CACHE_DIR, "index.json")

def _load_index() -> dict:
    p = _cache_index_path()
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_index(idx: dict):
    with open(_cache_index_path(), "w") as f:
        json.dump(idx, f)

def get_cached_video(file_id: str) -> str | None:
    """Return cached file path if fresh, else None."""
    idx = _load_index()
    key = _cache_key(file_id)
    if key in idx:
        entry = idx[key]
        path  = entry["path"]
        saved = entry["ts"]
        if os.path.exists(path) and (time.time() - saved) < CACHE_TTL:
            return path
        # Stale — remove
        try:
            os.remove(path)
        except Exception:
            pass
        del idx[key]
        _save_index(idx)
    return None

def store_cached_video(file_id: str, path: str):
    idx = _load_index()
    idx[_cache_key(file_id)] = {"path": path, "ts": time.time()}
    _save_index(idx)

def purge_stale_cache():
    """Remove entries older than CACHE_TTL (run at startup and periodically)."""
    idx  = _load_index()
    now  = time.time()
    dead = [k for k, v in idx.items() if (now - v["ts"]) >= CACHE_TTL or not os.path.exists(v["path"])]
    for k in dead:
        try:
            os.remove(idx[k]["path"])
        except Exception:
            pass
        del idx[k]
    if dead:
        _save_index(idx)


# ─────────────────────────────────────────────
# 3. PROGRESS BAR
# ─────────────────────────────────────────────
async def progress_bar(current: int, total: int, status_msg, start_time: float, action: str):
    chat_id = status_msg.chat.id
    if chat_id in _cancelled:
        raise Exception("STOP_PROCESS")
    now = time.time()
    if current != total and now - _last_edit.get(status_msg.id, 0) < 4:
        return
    _last_edit[status_msg.id] = now
    diff       = max(now - start_time, 0.001)
    percentage = current * 100 / total
    speed      = current / diff
    eta        = int((total - current) / speed) if speed > 0 else 0

    def fmt_time(secs: int):
        h, rem = divmod(secs, 3600)
        m, s   = divmod(rem, 60)
        return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    filled = int(10 * current / total)
    bar    = "■" * filled + "□" * (10 - filled)
    text   = (f"**Progress :** `[{bar}]` **{percentage:.1f}%**\n"
              f"**{action} :** `{current/1048576:.1f} MB` | `{total/1048576:.1f} MB`\n"
              f"**Speed :** `{speed/1048576:.2f} MB/s`\n"
              f"**ETA :** `{fmt_time(eta)}`\n"
              f"**Time elapsed :** `{fmt_time(int(diff))}`")
    try:
        await status_msg.edit(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✖️ CANCEL ✖️", callback_data="stop_all")]]
            ),
        )
    except Exception:
        pass


# ─────────────────────────────────────────────
# 4. FAST DOWNLOAD  (aria2c → pyrogram fallback)
# ─────────────────────────────────────────────
async def fast_download(client, msg, dest_path: str, status_msg, label: str) -> str:
    """
    Download Telegram media to dest_path as fast as possible.
    Uses pyrogram's download_media with concurrent chunk workers (workers=100 already set).
    Returns the final file path.
    """
    chat_id = status_msg.chat.id
    start   = time.time()

    # Pyrogram's built-in downloader is multi-part when workers > 1
    path = await client.download_media(
        msg,
        file_name=dest_path,
        progress=progress_bar,
        progress_args=(status_msg, start, label),
    )
    return path


# ─────────────────────────────────────────────
# 5. LEECH SERVER  — serve large files over HTTP
# ─────────────────────────────────────────────
class _LeechHandler(http.server.SimpleHTTPRequestHandler):
    """Serve files from LEECH_DIR and CACHE_DIR."""
    def translate_path(self, path):
        # strip query string
        path = path.split("?", 1)[0].split("#", 1)[0]
        # leech/<filename>  →  LEECH_DIR/<filename>
        if path.startswith("/leech/"):
            return os.path.join(LEECH_DIR, os.path.basename(path))
        # cache/<filename>  →  CACHE_DIR/<filename>
        if path.startswith("/cache/"):
            return os.path.join(CACHE_DIR, os.path.basename(path))
        return super().translate_path(path)

    def log_message(self, *args):
        pass  # silence access logs


def start_server():
    with socketserver.TCPServer(("", 7860), _LeechHandler) as httpd:
        httpd.serve_forever()


def leech_url(filename: str) -> str:
    base = PUBLIC_URL if PUBLIC_URL else "http://localhost:7860"
    return f"{base}/leech/{filename}"


def move_to_leech(src_path: str) -> tuple[str, str]:
    """
    Move finished output file to LEECH_DIR and return (dest_path, public_url).
    Purge leech files older than CACHE_TTL while we're at it.
    """
    # Purge old leech files
    now = time.time()
    for fn in os.listdir(LEECH_DIR):
        fp = os.path.join(LEECH_DIR, fn)
        try:
            if now - os.path.getmtime(fp) > CACHE_TTL:
                os.remove(fp)
        except Exception:
            pass
    dest = os.path.join(LEECH_DIR, os.path.basename(src_path))
    shutil.move(src_path, dest)
    return dest, leech_url(os.path.basename(dest))


# ─────────────────────────────────────────────
# 6. PROCESSING CORE
# ─────────────────────────────────────────────
async def finalize_mux(client, message, chat_id: int, data: dict):
    work_dir = f"work_mux_{chat_id}_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)

    # Clean bot-prompt messages
    if "msg_ids" in data:
        asyncio.create_task(client.delete_messages(chat_id, data["msg_ids"]))

    status = await client.send_message(chat_id, "🚀 **Initializing Mux Pipeline...**")
    try:
        # ── Video: use cache if available ──────────────────────────
        v_msg    = await client.get_messages(chat_id, data["vid_id"])
        file_id  = (v_msg.video or v_msg.document).file_id
        cached   = get_cached_video(file_id)

        if cached:
            await status.edit("📂 **Using cached video (saved download time)...**")
            v_path = cached
        else:
            await status.edit("📥 **Downloading video...**")
            raw_path = os.path.join(CACHE_DIR, f"{_cache_key(file_id)}.mp4")
            v_path   = await fast_download(client, v_msg, raw_path, status, "Download")
            store_cached_video(file_id, v_path)

        # ── Subtitle ───────────────────────────────────────────────
        s_msg  = await client.get_messages(chat_id, data["sub_id"])
        s_path = await client.download_media(s_msg, file_name=f"{work_dir}/s.ass")

        # ── Thumbnail ─────────────────────────────────────────────
        th = None
        if message.photo:
            th = await client.download_media(message.photo, file_name=f"{work_dir}/t.jpg")

        # ── FFmpeg mux ─────────────────────────────────────────────
result = subprocess.run([out = os.path.join(work_dir, data["out_name"])

result = subprocess.run(
    [
        "ffmpeg",
        "-y",
        "-i", v_path,
        "-i", s_path,
        "-map", "0:v",
        "-map", "0:a?",
        "-map", "1:s:0",
        "-c:v", "copy",
        "-c:a", "copy",
        "-c:s", "ass",
        "-metadata:s:s:0", "title=ENGLISH @TheFrictionRealm",
        out,
    ],
    capture_output=True,
    text=True,
)

if result.returncode != 0:
    raise Exception(f"FFmpeg failed:\n{result.stderr}")

if not os.path.exists(out) or os.path.getsize(out) == 0:
    raise Exception("Mux failed: Output file is empty")

        # ── Decide: upload or leech ────────────────────────────────
        out_size = os.path.getsize(out)
        if out_size > SIZE_2GB:
            await status.edit("📦 **File > 2 GB — moving to leech server...**")
            _, url = move_to_leech(out)
            caption = generate_friction_caption(data["out_name"])
            leech_text = (
                f"{caption}\n\n"
                f"📁 **Size:** `{out_size/1073741824:.2f} GB`\n"
                f"🔗 **Leech Link (2h):**\n`{url}`"
            )
            await client.send_message(chat_id, leech_text)
        else:
            await status.edit("📤 **Uploading to Telegram...**")
            await client.send_document(
                chat_id, out,
                thumb=th,
                caption=generate_friction_caption(data["out_name"]),
                progress=progress_bar,
                progress_args=(status, time.time(), "Upload"),
            )

    except Exception as e:
        if "STOP_PROCESS" in str(e):
            await status.edit("🛑 **Process Cancelled.**")
        else:
            await client.send_message(chat_id, f"❌ **Error:**\n`{traceback.format_exc()}`")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        _cancelled.discard(chat_id)
        try:
            await status.delete()
        except Exception:
            pass


async def start_sub_process(client, msg, chat_id: int, task: str, data: dict):
    work_dir = f"work_sub_{chat_id}_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)

    if "msg_ids" in data:
        asyncio.create_task(client.delete_messages(chat_id, data["msg_ids"]))

    status = await client.send_message(chat_id, "⏳ **Processing Subtitle...**")
    try:
        s_msg = await client.get_messages(chat_id, data["sub_id"])
        s_p   = await client.download_media(s_msg, file_name=f"{work_dir}/i.srt")
        ext   = "ass" if task == "style" else data["ext"]
        out   = os.path.join(work_dir, f"{data['orig_sub_name'].rsplit('.', 1)[0]}.{ext}")

        if task == "style":
            temp = os.path.join(work_dir, "t.ass")
            subprocess.run(["ffmpeg", "-i", s_p, temp, "-y"], check=True)
            with open(temp, "r", encoding="utf-8") as f:
                lines = f.readlines()
            ev_idx = next(i for i, l in enumerate(lines) if "[Events]" in l)
            with open(out, "w", encoding="utf-8") as f:
                f.write(data["header"] + "\n\n" + "".join(lines[ev_idx:]))
        else:
            subprocess.run(["ffmpeg", "-i", s_p, out, "-y"], check=True)

        await client.send_document(chat_id, out, caption="✅ **Subtitle Ready!**")
    except Exception as e:
        await client.send_message(chat_id, f"❌ **Error:**\n`{traceback.format_exc()}`")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        try:
            await status.delete()
        except Exception:
            pass


# ─────────────────────────────────────────────
# 7. HANDLERS
# ─────────────────────────────────────────────
@app.on_message(
    filters.command(["style", "convert", "mux", "speed", "cache"]) &
    filters.private &
    filters.user(AUTHORIZED_USERS)
)
async def cmd_handler(client, message):
    mode = message.command[0].lower()

    # Speed test
    if mode == "speed":
        try:
            import speedtest
            m    = await message.reply("🚀 **Testing Speed...**")
            loop = asyncio.get_running_loop()
            st   = await loop.run_in_executor(None, speedtest.Speedtest)
            await loop.run_in_executor(None, st.get_best_server)
            dl   = await loop.run_in_executor(None, st.download)
            ul   = await loop.run_in_executor(None, st.upload)
            await m.edit(
                f"📊 **HF Speed:**\n"
                f"📥 DL: `{dl/1048576:.2f} MB/s` | 📤 UL: `{ul/1048576:.2f} MB/s`"
            )
        except Exception as e:
            await message.reply(f"❌ Speed test failed: `{e}`")
        return

    # Cache info / purge
    if mode == "cache":
        purge_stale_cache()
        idx   = _load_index()
        count = len(idx)
        total = sum(
            os.path.getsize(v["path"])
            for v in idx.values()
            if os.path.exists(v["path"])
        )
        await message.reply(
            f"📦 **Video Cache Status**\n"
            f"Files: `{count}`\n"
            f"Size: `{total/1048576:.1f} MB`\n"
            f"TTL: `2 hours`\n\n"
            f"Stale files purged automatically."
        )
        return

    user_data[message.from_user.id] = {
        "mode": mode,
        "step": "video" if mode == "mux" else "sub",
        "msg_ids": [message.id],
    }

    if mode == "mux":
        m = await message.reply("📦 **Mux Mode Active.**\n\nSend the video file to mux.")
    else:
        m = await message.reply(
            f"🎨 **{mode.title()} Mode Active.**\n\nSend the .srt/.ass subtitle file."
        )
    user_data[message.from_user.id]["msg_ids"].append(m.id)


@app.on_callback_query(filters.user(AUTHORIZED_USERS))
async def cb_handler(client, cb):
    chat_id = cb.from_user.id
    if cb.data == "stop_all":
        _cancelled.add(chat_id)
        user_data.pop(chat_id, None)
        await cb.message.edit("🛑 **Terminated.**")
        return

    data = user_data.pop(chat_id, None)
    if not data:
        return

    if "msg_ids" in data:
        data["msg_ids"].append(cb.message.id)

    if cb.data.startswith("st_"):
        data["header"] = HEADER_CINEMATIC if "cin" in cb.data else HEADER_FULL_4K
        asyncio.create_task(start_sub_process(client, cb.message, chat_id, "style", data))
    elif cb.data.startswith("cv_"):
        data["ext"] = cb.data.split("_")[1]
        asyncio.create_task(start_sub_process(client, cb.message, chat_id, "convert", data))


@app.on_message(
    filters.private &
    ~filters.command(["style", "convert", "mux", "speed", "cache"]) &
    filters.user(AUTHORIZED_USERS)
)
async def main_handler(client, message):
    chat_id = message.from_user.id
    if chat_id not in user_data:
        return
    data = user_data[chat_id]

    if data["mode"] in ("style", "convert") and data["step"] == "sub" and message.document:
        data.update({"sub_id": message.id, "orig_sub_name": message.document.file_name})
        if data["mode"] == "style":
            btns = [[
                InlineKeyboardButton("🎞 Cinematic", callback_data="st_cin"),
                InlineKeyboardButton("📺 Full 4K",   callback_data="st_full"),
            ]]
        else:
            btns = [[
                InlineKeyboardButton("📄 To SRT", callback_data="cv_srt"),
                InlineKeyboardButton("💎 To ASS",  callback_data="cv_ass"),
            ]]
        m = await message.reply("Select Subtype:", reply_markup=InlineKeyboardMarkup(btns))
        data["msg_ids"].append(m.id)

    elif data["mode"] == "mux":
        if data["step"] == "video" and (message.video or message.document):
            data.update({"vid_id": message.id, "step": "sub"})
            # Peek at file size immediately and warn if >2 GB
            media  = message.video or message.document
            size   = media.file_size or 0
            note   = ""
            if size > SIZE_2GB:
                note = (f"\n\n⚠️ **File is `{size/1073741824:.2f} GB` (> 2 GB).**\n"
                        f"After muxing it will be served as a **leech link** instead of uploading to Telegram.")
            m = await message.reply(f"✅ **Video received.** Now send the .ass subtitle.{note}")
            data["msg_ids"].append(m.id)

        elif data["step"] == "sub" and message.document:
            data.update({"sub_id": message.id, "step": "name"})
            m = await message.reply("✅ **Subtitle received.**\n\nType the final output name (without extension):")
            data["msg_ids"].append(m.id)

        elif data["step"] == "name" and message.text:
            data.update({"out_name": message.text + ".mkv", "step": "thumb"})
            m = await message.reply("🖼 **Send a thumbnail (photo) or type** `/skip` **to proceed without one.**")
            data["msg_ids"].append(m.id)

        elif data["step"] == "thumb":
            if message.photo or (message.text and "/skip" in message.text):
                task_data = user_data.pop(chat_id)
                asyncio.create_task(finalize_mux(client, message, chat_id, task_data))


# ─────────────────────────────────────────────
# 8. STARTUP
# ─────────────────────────────────────────────
threading.Thread(target=start_server, daemon=True).start()

# Purge any stale cache from a previous run
purge_stale_cache()

app.run()
