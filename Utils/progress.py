import time

def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.2f} {unit}"
        num /= 1024

def build_bar(current: int, total: int, start: float) -> str:
    total = max(total, 1)
    current = max(min(current, total), 0)
    percent = (current / total) * 100
    filled = int(percent // 5)
    bar = "■" * filled + "□" * (20 - filled)
    elapsed = max(time.time() - start, 0.001)
    speed = current / elapsed
    remaining = max(total - current, 0)
    eta = remaining / speed if speed > 0 else 0
    return (
        f"[{bar}] {percent:.2f}%\n"
        f"{human_size(current)} / {human_size(total)}\n"
        f"Speed: {human_size(speed)}/s\n"
        f"ETA: {int(eta)}s\n"
        f"Elapsed: {int(elapsed)}s"
    )
