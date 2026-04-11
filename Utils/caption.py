from __future__ import annotations
import re

QUALITY_RE = re.compile(r"(2160p|1080p|720p|480p|4K|8K|2K)", re.I)
EP_RE = re.compile(r"(?:EP(?:ISODE)?\s*|E\s*)(\d{1,4})", re.I)

def clean_title(name: str) -> str:
    base = name.rsplit(".", 1)[0]
    base = re.sub(r"\[[^\]]*\]", " ", base)
    base = re.sub(r"\([^\)]*\)", " ", base)
    base = re.sub(r"[._]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base

def generate_caption(filename: str) -> str:
    title = clean_title(filename)
    ep = EP_RE.search(filename)
    q = QUALITY_RE.search(filename)
    quality = q.group(1).upper() if q else "UNKNOWN"
    episode = ep.group(1) if ep else "?"
    return f"{title}\nEPISODE {episode}\n{quality}\nSUBTITLE : INBUILT"
