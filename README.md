---
title: FrictionBot
emoji: 🤖
colorFrom: purple
colorTo: blue
sdk: docker
app_file: bot.py
pinned: false
---

# Friction Mux Bot

Telegram mux bot for Hugging Face Spaces with:
- access control
- muxing
- subtitle handling
- cache
- leech server
- speed test
- cancel support

## Environment variables

Set these in the Space settings:

```bash
API_ID=123456
API_HASH=your_api_hash
BOT_TOKEN=123456:bot_token
OWNER_ID=123456789
AUTHORIZED_USERS=123456789 987654321
PUBLIC_URL=https://your-space-name.hf.space
HTTP_PORT=7860
