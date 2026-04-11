from __future__ import annotations
import os
import shutil
from pathlib import Path
from config import WORK_DIR

def ensure_dirs() -> None:
    Path(WORK_DIR).mkdir(parents=True, exist_ok=True)

def cleanup_path(path: str | None) -> None:
    if not path:
        return
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

def cleanup_job(paths: list[str | None]) -> None:
    for path in paths:
        cleanup_path(path)
