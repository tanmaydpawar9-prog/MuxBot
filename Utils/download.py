from __future__ import annotations
import asyncio
import os
from pathlib import Path

from config import WORK_DIR

async def aria2_download(url: str, output_name: str, aria2_opts: list[str] | None = None) -> str:
    Path(WORK_DIR).mkdir(parents=True, exist_ok=True)
    out = os.path.join(WORK_DIR, output_name)
    cmd = [
        "aria2c",
        "--console-log-level=warn",
        "--summary-interval=2",
        "-x", "16",
        "-s", "16",
        "-k", "1M",
        "-c",
        "--auto-file-renaming=false",
        "--allow-overwrite=true",
        "-d", WORK_DIR,
        "-o", output_name,
        url,
    ]
    if aria2_opts:
        cmd[1:1] = aria2_opts
    proc = await asyncio.create_subprocess_exec(*cmd)
    rc = await proc.wait()
    if rc != 0:
        raise RuntimeError(f"aria2c failed with code {rc}")
    return out

async def download_telegram_media(message, dest_dir: str) -> str:
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    return await message.download_media(file=dest_dir)
