from __future__ import annotations
import asyncio
import os
import time
from pathlib import Path
from telethon import events

from config import WORK_DIR
from utils.access import is_authorized
from utils.progress import human_size

async def _write_test_file(path: str, size_mb: int = 32) -> None:
    chunk = b"0" * (1024 * 1024)
    with open(path, "wb") as f:
        for _ in range(size_mb):
            f.write(chunk)

async def register_speed_handlers(client, state_store):
    @client.on(events.NewMessage(pattern=r"^/speed$"))
    async def speed_cmd(event):
        if not is_authorized(event.sender_id):
            return

        Path(WORK_DIR).mkdir(parents=True, exist_ok=True)
        test_path = os.path.join(WORK_DIR, "speed_test.bin")
        size_mb = 16
        await _write_test_file(test_path, size_mb=size_mb)

        start = time.time()
        await client.send_file(event.chat_id, test_path, caption="Speed test upload")
        elapsed = max(time.time() - start, 0.001)
        speed = os.path.getsize(test_path) / elapsed / 1024 / 1024

        await event.reply(
            f"Upload test: {speed:.2f} MB/s\n"
            f"File size: {size_mb} MB"
        )
