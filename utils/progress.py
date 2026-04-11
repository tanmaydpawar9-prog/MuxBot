import time

def format_size(bytes_val):
    mb = bytes_val / (1024 * 1024)
    return f"{mb:.2f} MB"


class ProgressTracker:
    def __init__(self):
        self.start_time = time.time()

    def render(self, action, current, total):
        if total == 0:
            return f"{action}ing... {format_size(current)}"
        
        percent = current * 100 / total
        elapsed = time.time() - self.start_time
        speed = current / elapsed if elapsed > 0 else 0
        eta = (total - current) / speed if speed > 0 else 0
        
        filled = int(percent / 10)
        bar = "■" * filled + "□" * (10 - filled)
        
        return (
            f"<b>{action}ing...</b>\n"
            f"<code>[{bar}] {percent:.1f}%</code>\n"
            f"<b>Size:</b> {format_size(current)} / {format_size(total)}\n"
            f"<b>Speed:</b> {format_size(speed)}/s\n"
            f"<b>ETA:</b> {int(eta)}s"
        )
