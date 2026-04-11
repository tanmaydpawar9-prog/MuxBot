---

title: Friction Mux Bot
emoji: 🤖
colorFrom: purple
colorTo: blue
sdk: python
python_version: "3.10"
app_file: bot.py
pinned: false

🚀 Friction Mux Bot (Ultra Pro)

A high-performance Telegram mux bot with subtitle support, caching, leech server, and async processing — optimized for Hugging Face Spaces.

---

⚙️ Hugging Face Setup

🧩 Space Settings

- SDK: Python
- Hardware: CPU (16GB recommended)
- Port: 7860 (auto-used)

---

🔐 Environment Variables

Go to Settings → Variables and add:

API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token

OWNER_ID=your_telegram_user_id
AUTHORIZED_USERS=123456789 987654321

PUBLIC_URL=https://your-space-name.hf.space

---

▶️ Run Command

CMD ["python", "bot.py"]
---

📦 Requirements

System Dependencies (IMPORTANT)

Make sure your Space has:

- ffmpeg
- aria2

If not, switch to Docker Space (recommended for full performance)

---

Python Dependencies

Installed via "requirements.txt":

telethon
aiohttp

---

🎬 Features

🔐 Access Control

- Only OWNER + AUTHORIZED_USERS allowed

---

🎬 Mux System

- Softsub ".ass" → ".mkv"
- No re-encode ("-c copy")
- Works with or without audio
- Metadata:
  ENGLISH @TheFrictionRealm

---

⏳ Flexible Subtitle Flow

After "/mux":

- Send subtitle later
- Download subtitle via URL
- Skip subtitle

---

⚡ High-Speed Download

- aria2 multi-threaded download
- Async processing

---

📊 Progress System

- Progress bar (■ □)
- Speed (MB/s)
- ETA + elapsed time

---

🧠 Smart Cache

- file_id reuse
- TTL: 2 hours
- "/cache" command

---

🌐 Leech Server

- Files >2GB automatically served via HTTP
- Public links generated

Example:

https://your-space.hf.space/filename.mkv

---

🛑 Cancel System

- Inline button: ✖️ CANCEL ✖️
- Stops:
  - Download
  - Upload
  - Processing

---

🧹 Auto Cleanup

- Deletes temp files after every task
- Prevents storage overflow

---

🎨 Subtitle Tools

- "/convert" → format conversion
- "/style" → convert to ".ass"

---

⚡ Speed Test

- "/speed"
- Measures upload performance

---

⚠️ Important Notes

- Telegram upload speed is the main bottleneck
- Hugging Face disk speed affects performance
- Large mux jobs require enough storage

---

🧪 Debugging

If bot fails:

- Check logs in HF Space
- Verify environment variables
- Ensure:
  - ffmpeg installed
  - aria2 installed

---

✅ Status

✔ Production Ready
✔ Async Safe
✔ Multi-user Support
✔ Hugging Face Compatible

---

💡 Performance Tips

- Avoid running many mux jobs at once
- Use smaller test files first
- Monitor HF logs for bottlenecks

---

Enjoy 🚀
