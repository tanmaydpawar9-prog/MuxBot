# Friction Mux Bot Final Pro

## Features
- Access control via OWNER_ID and AUTHORIZED_USERS
- /mux flow with delayed subtitle support
- Subtitle online download button/URL flow
- Skip subtitle flow
- Softsub mux into MKV
- Cache and purge command
- Leech server for files larger than Telegram limit
- Subtitle convert/style commands
- Speed test command

## Runtime requirements
- ffmpeg
- aria2c

## Deploy
Set environment variables from `.env.example`, then run:
```bash
python bot.py
```
