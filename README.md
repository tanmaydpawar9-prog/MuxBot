# 🎬 MuxBot

Telegram bot for muxing, styling, and converting subtitles — built for donghua content.

## 🚀 Features

| Command | What it does |
|---|---|
| `/mux` | Mux video + `.ass` subtitle (no re-encode), optional thumbnail, custom filename |
| `/style` | Inject Cinematic (816p) or Full 4K (1080p) ASS styles into `.srt`/`.ass` |
| `/convert` | Convert `.srt ↔ .ass` via FFmpeg |

- Exact progress bar: `[■■■■□□□□□□] 45.2%` with speed, ETA, size
- ✖️ CANCEL ✖️ inline button stops download / mux / upload
- Smart caption extraction (EP number, quality tag, clean title)
- Per-user state machine (multi-step flows)
- HF Keep-alive on port 7860
- Access control via `OWNER_ID` / `ALLOWED_USERS`

## ⚙️ Environment Variables

```
API_ID=
API_HASH=
BOT_TOKEN=
OWNER_ID=
ALLOWED_USERS=123456,789012   # comma-separated, optional
```

## 🐳 Run with Docker

```bash
docker build -t muxbot .
docker run -e API_ID=... -e API_HASH=... -e BOT_TOKEN=... -e OWNER_ID=... muxbot
```

## 📁 Structure

```
MuxBot/
├── main.py           # All handlers
├── config.py         # Env config + access control
├── core/
│   ├── downloader.py # Telegram download + progress
│   ├── uploader.py   # Telegram upload + progress
│   └── workflow.py   # Per-user state machine
├── utils/
│   ├── caption.py    # Smart caption extractor
│   ├── ffmpeg.py     # Mux / style / convert logic
│   └── progress.py   # Exact progress bar renderer
├── Dockerfile
└── requirements.txt
```
