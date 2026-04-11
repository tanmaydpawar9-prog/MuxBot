from __future__ import annotations
import os
from telethon import events

from config import WORK_DIR
from utils.access import is_authorized
from utils.ffmpeg import convert_subtitle, style_subtitle
from utils.cleanup import ensure_dirs

async def register_subtitle_handlers(client, state_store):
    ensure_dirs()

    @client.on(events.NewMessage(pattern=r"^/convert$"))
    async def convert_cmd(event):
        if not is_authorized(event.sender_id):
            return
        await event.reply("Send subtitle file to convert: .srt / .ass / .vtt")

    @client.on(events.NewMessage(pattern=r"^/style$"))
    async def style_cmd(event):
        if not is_authorized(event.sender_id):
            return
        await event.reply("Send subtitle file to style. Default output will be .ass")

    @client.on(events.NewMessage)
    async def subtitle_router(event):
        if not event.is_private or not is_authorized(event.sender_id):
            return
        txt = (event.raw_text or "").strip()
        if not event.file:
            return

        name = (event.file.name or "subtitle").lower()
        if not (name.endswith(".srt") or name.endswith(".ass") or name.endswith(".vtt")):
            return

        inp = await event.download_media(file=WORK_DIR)
        base = os.path.splitext(os.path.basename(inp))[0]

        if any(cmd in txt.lower() for cmd in ("/convert",)):
            if name.endswith(".srt"):
                out = os.path.join(WORK_DIR, base + ".ass")
                await convert_subtitle(inp, out)
            elif name.endswith(".ass"):
                out = os.path.join(WORK_DIR, base + ".srt")
                await convert_subtitle(inp, out)
            else:
                out = os.path.join(WORK_DIR, base + ".srt")
                await convert_subtitle(inp, out)
            await event.reply(file=out)

        elif any(cmd in txt.lower() for cmd in ("/style",)):
            out = os.path.join(WORK_DIR, base + ".ass")
            await style_subtitle(inp, out)
            await event.reply(file=out)
