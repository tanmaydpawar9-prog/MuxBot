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
            Button.inline("⬇️ Download Video", data=b"download_video"),
            Button.inline("⏭ Skip Subtitle", data=b"sub_skip"),
        ],
        [
            Button.inline("✖️ CANCEL ✖️", data=b"cancel"),
        ],
    ]


async def _ask_sub_options(event):
    await event.reply(
        "Send subtitle (.ass) or choose:",
        buttons=_subtitle_buttons(),
    )


async def register_mux_handlers(client, state_store: dict[int, JobState]):
    ensure_dirs()

    @client.on(events.NewMessage(pattern=r"^/mux$"))
    async def mux_start(event):
        if not is_authorized(event.sender_id):
            return

        state_store[event.sender_id] = JobState(stage="waiting_video")
        await event.reply("Send the video file.")

    @client.on(events.NewMessage)
    async def mux_router(event):
        if not event.is_private or not is_authorized(event.sender_id):
            return

        uid = event.sender_id
        text = (event.raw_text or "").strip()
        st = state_store.get(uid)

        if not st:
            return

        try:
            # =============================
            # VIDEO RECEIVED (NO DOWNLOAD)
            # =============================
            if st.stage == "waiting_video" and event.video:
                st.video_file = event.message

                st.stage = "waiting_subtitle"

                await event.reply("✅ Video received.")
                await _ask_sub_options(event)
                return

            # =============================
            # SUBTITLE FILE
            # =============================
            if st.stage == "waiting_subtitle":

                if event.file:
                    st.subtitle_file = event.message
                    st.stage = "waiting_output"
                    await event.reply("Send output name.")
                    return

                return

            # =============================
            # OUTPUT NAME
            # =============================
            if st.stage == "waiting_output" and text and not text.startswith("/"):
                st.output_name = text + ".mkv"
                st.stage = "processing"

                progress = await event.reply("⚙️ Processing...")

                async def run():
                    try:
                        # DOWNLOAD VIDEO NOW
                        msg = await event.reply("📥 Downloading video...")
                        video_path = await download_telegram_media(
                            st.video_file, WORK_DIR
                        )
                        await msg.edit("✅ Video downloaded.")

                        # DOWNLOAD SUBTITLE IF EXISTS
                        subtitle_path = None
                        if getattr(st, "subtitle_file", None):
                            msg2 = await event.reply("📥 Downloading subtitle...")
                            subtitle_path = await download_telegram_media(
                                st.subtitle_file, WORK_DIR
                            )
                            await msg2.edit("✅ Subtitle ready.")

                        out = os.path.join(WORK_DIR, st.output_name)

                        muxed = await mux_subtitles(
                            video_path,
                            out,
                            subtitle=subtitle_path,
                        )

                        size = os.path.getsize(muxed)
                        caption = generate_caption(st.output_name)

                        if size <= MAX_TG_SIZE:
                            await send_document(
                                client,
                                event.chat_id,
                                muxed,
                                caption=caption,
                                progress_message=progress,
                                user_id=uid,
                            )
                        else:
                            Path(LEECH_DIR).mkdir(parents=True, exist_ok=True)
                            leech = os.path.join(
                                LEECH_DIR, os.path.basename(muxed)
                            )
                            os.replace(muxed, leech)

                            await event.reply(
                                f"{PUBLIC_URL}/{os.path.basename(leech)}"
                            )

                    except Exception as e:
                        await event.reply(f"❌ Error: {str(e)}")

                    finally:
                        pop(uid)
                        state_store.pop(uid, None)

                task = asyncio.create_task(run())
                register(uid, task)
                return

        except Exception as e:
            await event.reply(f"❌ {str(e)}")

    # =============================
    # BUTTONS
    # =============================

    @client.on(events.CallbackQuery(data=b"download_video"))
    async def _(event):
        await event.answer("Video will be downloaded during processing.")

    @client.on(events.CallbackQuery(data=b"sub_skip"))
    async def _(event):
        uid = event.sender_id
        st = state_store.get(uid)

        if st:
            st.subtitle_file = None
            st.stage = "waiting_output"

        await event.answer("Subtitle skipped. Send output name.")

    @client.on(events.CallbackQuery(data=b"cancel"))
    async def _(event):
        uid = event.sender_id
        cancel(uid)

        state_store.pop(uid, None)

        await event.answer("Cancelled")
