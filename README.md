🚀 Friction Mux Bot (Ultra Pro - HF Ready)

A high-performance Telegram mux bot with subtitle handling, leech server, caching, and async processing — optimized for Hugging Face Spaces.

---

⚙️ Runtime Configuration (Hugging Face Spaces)

🧩 Space Settings

- SDK: Docker (recommended) OR Python
- Hardware: CPU (16GB RAM recommended)
- Port: "7860"

---

📦 Required Dependencies

Make sure these are available in your Space:

System Packages

ffmpeg
aria2

Python Packages (auto-installed via requirements.txt)

telethon
aiohttp

---

🔐 Environment Variables

Set these in HF Space → Settings → Variables

API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token

OWNER_ID=your_telegram_id
AUTHORIZED_USERS=123456789 987654321

PUBLIC_URL=https://your-space-name.hf.space
HTTP_PORT=7860

---

▶️ Startup Command

CMD ["python", "bot.py"]

---

🌐 Leech Server

- Runs automatically on port "7860"
- Files >2GB are served via:

https://your-space.hf.space/<filename>

---

🎬 Features

🔐 Access Control

- Only OWNER + AUTHORIZED_USERS allowed

🎬 Mux System

- Softsub ".ass" → ".mkv"
- "-c copy" (no re-encode)
- Works with/without audio
- Metadata: "ENGLISH @TheFrictionRealm"

⏳ Flexible Subtitle Flow

After "/mux":

- Send subtitle later
- Download subtitle via URL
- Skip subtitle

⚡ High-Speed System

- aria2 multi-thread download
- async processing

📊 Progress System

- Speed, ETA, progress bar

🧠 Cache System

- file_id reuse
- TTL: 2 hours
- "/cache" command

🌐 Leech System

- Auto for files >2GB
- Direct HTTP access

🛑 Cancel System

- Inline button
- Stops active tasks

🧹 Auto Cleanup

- Clears temp files after task

🎨 Subtitle Tools

- "/convert"
- "/style"

⚡ Speed Test

- "/speed"

---

⚠️ Important Notes

- Telegram upload speed is the main bottleneck
- HF disk I/O can affect performance
- Ensure enough storage for large mux operations

---

🧪 Debugging

If bot doesn’t respond:

- Check logs in HF Space
- Verify environment variables
- Ensure ffmpeg + aria2 are installed

---

✅ Status

✔ Production Ready
✔ Async Safe
✔ Multi-user capable
✔ HF Compatible

---

💡 Tip

For maximum speed:

- Use high-quality HF hardware
- Avoid simultaneous heavy mux jobs

---

Enjoy 🚀
