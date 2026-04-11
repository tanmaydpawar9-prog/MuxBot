import asyncio
import os
import time
from pyrogram import Client
from pyrogram.enums import ParseMode
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
) -> str | None:
    tracker = ProgressTracker()
    last_edit = [0.0]

    media = message.document or message.video or message.audio or message.animation or message.photo
    if not media:
        return None
        
    file_size = getattr(media, "file_size", 0)
    file_name = getattr(media, "file_name", "downloaded_media")
    if not file_name:
        file_name = f"file_{message.id}"
        
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
                    await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
                except Exception:
                    pass

    try:
        # Parallel chunk downloading for massive files
        if file_size > 10 * 1024 * 1024:
            chunk_size = 1024 * 1024
            total_chunks = (file_size + chunk_size - 1) // chunk_size
            
            with open(output_path, "wb") as f:
                f.truncate(file_size) # Create sparse file instantly
                
            queue = asyncio.Queue()
            for i in range(total_chunks):
                queue.put_nowait((i, 0))  # (chunk_index, retries)
                
            downloaded = [0]
            error_event = asyncio.Event()
            
            async def worker():
                with open(output_path, "r+b") as f:
                    while not queue.empty() and not error_event.is_set():
                        if cancel_flag and cancel_flag.is_set():
                            break
                        chunk_idx, retries = await queue.get()
                        try:
                            data = b""
                            async for chunk in client.stream_media(message, limit=1, offset=chunk_idx):
                                data += chunk
                            if data:
                                f.seek(chunk_idx * chunk_size)
                                f.write(data)
                                downloaded[0] += len(data)
                                await progress(downloaded[0], file_size)
                        except Exception:
                            if retries < 3:
                                queue.put_nowait((chunk_idx, retries + 1))
                            else:
                                error_event.set()
                        finally:
                            queue.task_done()
                            
            tasks = [asyncio.create_task(worker()) for _ in range(5)]
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
                file_name=DOWNLOAD_DIR + "/",
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
