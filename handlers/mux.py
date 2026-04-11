from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from telethon import Button, events

from config import WORK_DIR, LEECH_DIR, MAX_TG_SIZE, PUBLIC_URL
from utils.access import is_authorized
from utils.state import JobState
from utils.download import aria2_download, download_telegram_media
from utils.ffmpeg import mux_subtitles
from utils.caption import generate_caption
from utils.upload import send_document
from utils.cancel import register, pop, cancel
from utils.cleanup import cleanup_job, ensure_dirs
from utils.cache import put


def _subtitle_buttons():
    return [
        [
            Button.inline("📎 Send subtitle later", data=b"sub_later"),
            Button.inline("⬇️ Download subtitle online", data=b"sub_online"),
        ],
        [
            Button.inline("⏭ Skip subtitle", data=b"sub_skip"),
        ],
        [
            Button.inline("✖️ CANCEL ✖️", data=b"cancel"),
        ],
    ]


async def _ask_sub_options(event):
    await event.reply(
        "Send subtitle (.ass), or choose one:",
        buttons=_subtitle_buttons(),
    )


async def _ask_thumbnail(event):
    await event.reply(
        "Send a thumbnail image now, or type /skip to continue without thumbnail."
    )


def _is_image_message(event) -> bool:
    if event.photo:
        return True
    if not event.file:
        return False
    mime = getattr(event.file, "mime_type", None)
    return bool(mime and mime.startswith("image/"))


async def register_mux_handlers(client, state_store: dict[int, JobState]):
    ensure_dirs()

    @client.on(events.NewMessage(pattern=r"^/mux$"))
    async def mux_start(event):
        if not is_authorized(event.sender_id):
            return

        state_store[event.sender_id] = JobState(stage="waiting_video")
        await event.reply("Send the video file you want to mux.")

    @client.on(events.NewMessage)
    async def mux_message_router(event):
        if not event.is_private or not is_authorized(event.sender_id):
            return

        uid = event.sender_id
        text = (event.raw_text or "").strip()
        st = state_store.get(uid)

        if not st:
            return

        try:
            # 1) waiting for video
            if st.stage == "waiting_video" and event.video:
                msg = await event.reply("📥 Downloading video...")

                try:
                    st.video_path = await download_telegram_media(
                        event.message, WORK_DIR
                    )
                except Exception as e:
                    await msg.edit(f"❌ Video download failed:\n{str(e)}")
                    return

                st.stage = "waiting_subtitle_choice"

                await msg.edit("✅ Video downloaded.")
                await _ask_sub_options(event)
                return

            # 2) waiting for subtitle
            if st.stage == "waiting_subtitle_choice":
                if event.file:
                    msg = await event.reply("📥 Downloading subtitle...")

                    try:
                        st.subtitle_path = await download_telegram_media(
                            event.message, WORK_DIR
                        )
                    except Exception as e:
                        await msg.edit(f"❌ Subtitle download failed:\n{str(e)}")
                        return

                    st.stage = "waiting_output_name"

                    await msg.edit("✅ Subtitle ready.")
                    await event.reply("Send output name (without extension).")
                    return

                if text.startswith("http://") or text.startswith("https://"):
                    st.subtitle_url = text
                    msg = await event.reply("⬇️ Downloading subtitle...")

                    try:
                        sub_name = f"{uuid.uuid4().hex}.ass"
                        st.subtitle_path = await aria2_download(text, sub_name)
                    except Exception as e:
                        await msg.edit(f"❌ Subtitle URL download failed:\n{str(e)}")
                        return

                    st.stage = "waiting_output_name"

                    await msg.edit("✅ Subtitle downloaded.")
                    await event.reply("Send output name (without extension).")
                    return

                return

            # 3) waiting for output name
            if st.stage == "waiting_output_name" and text and not text.startswith("/"):
                st.output_name = text.strip() + ".mkv"
                st.stage = "waiting_thumbnail"
                await _ask_thumbnail(event)
                return

            # 4) waiting for thumbnail or skip
            if st.stage == "waiting_thumbnail":
                if text.lower() == "/skip":
                    st.thumb_path = None
                    st.stage = "processing"
                elif _is_image_message(event):
                    msg = await event.reply("📥 Downloading thumbnail...")

                    try:
                        st.thumb_path = await download_telegram_media(
                            event.message, WORK_DIR
                        )
                    except Exception as e:
                        await msg.edit(f"❌ Thumbnail download failed:\n{str(e)}")
                        return

                    await msg.edit("✅ Thumbnail ready.")
                    st.stage = "processing"
                else:
                    await event.reply("Send a valid thumbnail image, or type /skip.")
                    return

                progress_msg = await event.reply("⚙️ Processing...")

                async def run_job():
                    try:
                        out_path = os.path.join(WORK_DIR, st.output_name)

                        muxed = await mux_subtitles(
                            st.video_path,
                            out_path,
                            subtitle=st.subtitle_path,
                            thumb=st.thumb_path,
                        )

                        size = os.path.getsize(muxed)
                        caption = generate_caption(st.output_name)

                        if size <= MAX_TG_SIZE:
                            await send_document(
                                client,
                                event.chat_id,
                                muxed,
                                caption=caption,
                                thumb=st.thumb_path,
                                progress_message=progress_msg,
                                user_id=uid,
                            )
                        else:
                            Path(LEECH_DIR).mkdir(parents=True, exist_ok=True)

                            leech_path = os.path.join(
                                LEECH_DIR, os.path.basename(muxed)
                            )

                            if os.path.exists(leech_path):
                                os.remove(leech_path)

                            os.replace(muxed, leech_path)

                            link = (
                                f"{PUBLIC_URL}/{os.path.basename(leech_path)}"
                                if PUBLIC_URL
                                else os.path.basename(leech_path)
                            )

                            await event.reply(f"📦 File too large.\nDownload: {link}")

                        put(st.task_id or str(uid), muxed)

                    except Exception as e:
                        await event.reply(f"❌ Error:\n{str(e)}")

                    finally:
                        cleanup_job([st.video_path, st.subtitle_path, st.thumb_path])
                        pop(uid)
                        state_store.pop(uid, None)

                task = asyncio.create_task(run_job())
                register(uid, task)
                return

        except Exception as e:
            await event.reply(f"❌ Unexpected Error:\n{str(e)}")

    @client.on(events.CallbackQuery(data=b"sub_later"))
    async def _(event):
        if not is_authorized(event.sender_id):
            return
        await event.answer("Send subtitle when ready.")

    @client.on(events.CallbackQuery(data=b"sub_online"))
    async def _(event):
        if not is_authorized(event.sender_id):
            return
        await event.answer("Send subtitle URL.")

    @client.on(events.CallbackQuery(data=b"sub_skip"))
    async def _(event):
        uid = event.sender_id
        st = state_store.get(uid)

        if st:
            st.subtitle_path = None
            st.stage = "waiting_output_name"

        await event.answer("Subtitle skipped.")

    @client.on(events.CallbackQuery(data=b"cancel"))
    async def _(event):
        if not is_authorized(event.sender_id):
            return

        uid = event.sender_id
        cancel(uid)
        st = state_store.get(uid)
        if st:
            st.stage = "idle"

        await event.answer("Cancelled")
        await event.edit("✖️ Cancelled.")
