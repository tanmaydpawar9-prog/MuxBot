from __future__ import annotations
import asyncio
import os
from pathlib import Path

from config import SUB_TITLE_TAG

async def run_ffmpeg(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(*cmd)
    rc = await proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed with code {rc}")

async def mux_subtitles(video: str, output: str, subtitle: str | None = None, thumb: str | None = None) -> str:
    cmd = ["ffmpeg", "-y", "-i", video]
    if subtitle:
        cmd += ["-i", subtitle, "-map", "0:v:0", "-map", "0:a?", "-map", "1:0"]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a?"]

    cmd += ["-c", "copy"]

    if subtitle:
        cmd += ["-metadata:s:s:0", f"title={SUB_TITLE_TAG}"]

    if thumb:
        cmd += ["-attach", thumb, "-metadata:s:t", "mimetype=image/jpeg"]

    cmd += [output]
    await run_ffmpeg(cmd)

    if not os.path.exists(output) or os.path.getsize(output) <= 0:
        raise RuntimeError("Mux produced an empty file")
    return output

async def convert_subtitle(input_path: str, output_path: str) -> str:
    cmd = ["ffmpeg", "-y", "-i", input_path, output_path]
    await run_ffmpeg(cmd)
    return output_path

async def style_subtitle(input_path: str, output_path: str, resolution: str = "1920x816", font_size: int = 48) -> str:
    # Minimal safe styling via ASS generation using ffmpeg conversion is not reliable for full styling.
    # This function keeps the original content and converts the container/extension appropriately.
    # For real styling, users can apply Aegisub templates externally.
    return await convert_subtitle(input_path, output_path)
