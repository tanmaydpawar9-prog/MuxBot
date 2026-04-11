import asyncio
import os
import re
import tempfile
import shutil

CINEMATIC_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX:

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,70,90,1,0,1,2,2,2,400,400,115,1
"""

FULL4K_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,70,90,1,0,1,2,2,2,400,400,120,1
"""

async def run_ffmpeg(*args):
    """Run FFmpeg with given arguments."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is not installed or not found in PATH.")
    
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{stderr.decode()}")
    return stdout, stderr


async def mux_video(video_path: str, sub_path: str, out_path: str, thumb_path: str = None):
    """Mux video + ASS subtitle (no re-encode), optional thumbnail."""
    inputs = ["-i", video_path, "-i", sub_path]
    maps = [
        "-map", "0:v", "-map", "0:a?",
        "-map", "1:s",
    ]
    meta = [
        "-metadata:s:s:0", "language=eng",
        "-metadata:s:s:0", "title=Default",
        "-disposition:s:0", "default",
    ]
    codec = ["-c", "copy", "-c:s", "ass"]

    if thumb_path:
        inputs += ["-i", thumb_path]
        maps += ["-map", "2:v"]
        codec += [
            "-c:v:1", "copy",
            "-disposition:v:1", "attached_pic",
        ]

    cmd = inputs + maps + meta + codec + [out_path]
    await run_ffmpeg(*cmd)


async def srt_to_ass_ffmpeg(srt_path: str, ass_path: str):
    """Basic SRT→ASS conversion via FFmpeg."""
    await run_ffmpeg("-i", srt_path, ass_path)


async def inject_style(input_path: str, output_path: str, mode: str):
    """
    input_path: .srt or .ass
    mode: 'cinematic' | 'full4k'
    Converts to ASS, then replaces [Script Info] + [V4+ Styles] block.
    """
    ext = os.path.splitext(input_path)[1].lower()

    # Convert SRT to ASS first if needed
    if ext == ".srt":
        tmp_ass = input_path.replace(".srt", "_tmp.ass")
        await srt_to_ass_ffmpeg(input_path, tmp_ass)
        working = tmp_ass
    else:
        working = input_path

    with open(working, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Extract [Events] block
    events_match = re.search(r"(\[Events\].*)", content, re.DOTALL)
    if not events_match:
        raise ValueError("Could not find [Events] block in subtitle file.")
    events_block = events_match.group(1)

    header = CINEMATIC_ASS_HEADER if mode == "cinematic" else FULL4K_ASS_HEADER
    final = header.rstrip() + "\n\n" + events_block.strip() + "\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final)

    # Cleanup tmp
    if ext == ".srt" and os.path.exists(tmp_ass):
        os.remove(tmp_ass)


async def convert_subtitle(input_path: str, output_path: str):
    """SRT ↔ ASS via FFmpeg."""
    await run_ffmpeg("-i", input_path, output_path)
