import time

def format_size(bytes_val):
    mb = bytes_val / (1024 * 1024)
    return f"{mb:.2f} MB"


def format_time(seconds):
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


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
        total_time = elapsed + eta
        
        filled = int(percent / 10)
        bar = "■" * filled + "□" * (10 - filled)
        
        return (
            f"<b>{action}ing...</b>\n"
            f"<code>[{bar}] {percent:.1f}%</code>\n"
            f"<b>Size:</b> {format_size(total)} | <b>Done:</b> {format_size(current)}\n"
            f"<b>Speed:</b> {format_size(speed)}/s\n"
            f"<b>ETA:</b> {format_time(eta)} | <b>Elapsed:</b> {format_time(elapsed)} | <b>Total:</b> {format_time(total_time)}"
        )
