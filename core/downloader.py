import asyncio
import os
import time
import math
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import Message
from utils.progress import ProgressTracker

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


async def download_media(
    client: Client,
    message: Message,
    status_msg: Message,
    cancel_flag: asyncio.Event,
    action: str = "Download",
    custom_name: str = None,
) -> str | None:
    tracker = ProgressTracker()
    last_edit = [0.0]

    media = message.document or message.video or message.audio or message.animation or message.photo
    if not media:
        return None
        
    file_size = getattr(media, "file_size", 0)
    orig_name = getattr(media, "file_name", "")
    ext = os.path.splitext(orig_name)[1] if orig_name else ".mp4"
    if not ext:
        ext = ".mp4"
        
    if custom_name:
        file_name = custom_name + ext
    else:
        file_name = orig_name if orig_name else f"file_{message.id}{ext}"

    output_path = os.path.join(DOWNLOAD_DIR, file_name)

    async def progress(current, total):
        if cancel_flag and cancel_flag.is_set():
            raise asyncio.CancelledError("Cancelled by user")
        now = time.time()
        if now - last_edit[0] >= 3.0:
            last_edit[0] = now
            text = tracker.render(action, current, total)
            if status_msg:
                try:
                    await status_msg.edit_text(
                        text, 
                        parse_mode=ParseMode.HTML,
                        reply_markup=status_msg.reply_markup
                    )
                except Exception:
                    pass

    try:
        # Parallel chunk downloading for massive files
        if file_size > 10 * 1024 * 1024:
            chunk_size = 1024 * 1024
            total_chunks = math.ceil(file_size / chunk_size)
            
            with open(output_path, "wb") as f:
                f.truncate(file_size) # Create sparse file instantly
                
            downloaded = [0]
            error_event = asyncio.Event()

            # Pre-auth and fetch first chunk sequentially to lock DC auth
            try:
                data = b""
                async for chunk in client.stream_media(message, limit=1, offset=0):
                    data += chunk
                if data:
                    with open(output_path, "r+b") as f:
                        f.seek(0)
                        f.write(data)
                    downloaded[0] += len(data)
                    await progress(downloaded[0], file_size)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception:
                pass
            
            if total_chunks > 1:
                remaining_chunks = total_chunks - 1
                workers = 3
                chunks_per_worker = math.ceil(remaining_chunks / workers)

                async def worker(start_chunk, end_chunk):
                    current_chunk = start_chunk
                    retries = 0
                    while current_chunk <= end_chunk and retries < 5 and not error_event.is_set():
                        if cancel_flag and cancel_flag.is_set():
                            break
                        try:
                            limit = end_chunk - current_chunk + 1
                            with open(output_path, "r+b") as f:
                                yielded_any = False
                                async for chunk in client.stream_media(message, limit=limit, offset=current_chunk):
                                    if cancel_flag and cancel_flag.is_set() or error_event.is_set():
                                        break
                                    f.seek(current_chunk * chunk_size)
                                    f.write(chunk)
                                    downloaded[0] += len(chunk)
                                    current_chunk += 1
                                    yielded_any = True
                                    await progress(downloaded[0], file_size)
                            if yielded_any:
                                retries = 0  # reset on success
                            else:
                                retries += 1
                                await asyncio.sleep(1)
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                        except Exception:
                            retries += 1
                            await asyncio.sleep(1)
                    
                    if retries >= 5:
                        error_event.set()

                tasks = []
                for i in range(workers):
                    start = 1 + i * chunks_per_worker
                    if start > total_chunks - 1:
                        break
                    end = min(start + chunks_per_worker - 1, total_chunks - 1)
                    tasks.append(asyncio.create_task(worker(start, end)))
                    
                if tasks:
                    await asyncio.gather(*tasks)
            
            if error_event.is_set():
                raise RuntimeError("Failed to download media chunks after multiple retries.")
                
            if cancel_flag and cancel_flag.is_set():
                if os.path.exists(output_path):
                    os.remove(output_path)
                raise asyncio.CancelledError("Cancelled by user")
                
            return output_path
        else:
            path = await client.download_media(
                message,
                file_name=output_path,
                progress=progress,
            )
            return path
    except asyncio.CancelledError:
        return None
    except Exception as e:
        if status_msg:
            try:
                await status_msg.edit_text(f"❌ Download failed:\n<code>{e}</code>", parse_mode=ParseMode.HTML)
            except Exception:
                pass
        return None
