from __future__ import annotations
import json
import os
import time
from pathlib import Path
from config import CACHE_INDEX, CACHE_TTL, CACHE_DIR

def _load() -> dict:
    path = Path(CACHE_INDEX)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save(data: dict) -> None:
    path = Path(CACHE_INDEX)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def put(file_id: str, path: str) -> None:
    data = _load()
    data[file_id] = {"path": path, "time": time.time()}
    _save(data)

def get(file_id: str) -> str | None:
    data = _load()
    item = data.get(file_id)
    if not item:
        return None
    if time.time() - item.get("time", 0) > CACHE_TTL:
        data.pop(file_id, None)
        _save(data)
        return None
    p = item.get("path")
    return p if p and os.path.exists(p) else None

def purge() -> tuple[int, int]:
    data = _load()
    now = time.time()
    kept = {}
    removed = 0
    total_size = 0

    for k, v in data.items():
        path = v.get("path")
        if not path or not os.path.exists(path):
            removed += 1
            continue
        age_ok = now - v.get("time", 0) <= CACHE_TTL
        if age_ok:
            kept[k] = v
            try:
                total_size += os.path.getsize(path)
            except Exception:
                pass
        else:
            removed += 1

    _save(kept)
    return removed, total_size

def stats() -> dict:
    data = _load()
    now = time.time()
    count = 0
    total_size = 0
    for v in data.values():
        path = v.get("path")
        if not path or not os.path.exists(path):
            continue
        if now - v.get("time", 0) <= CACHE_TTL:
            count += 1
            try:
                total_size += os.path.getsize(path)
            except Exception:
                pass
    return {"count": count, "size": total_size}
