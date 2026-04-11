import re

def extract_caption(filename: str) -> str:
    name = filename.rsplit(".", 1)[0]

    # Extract episode number
    ep_match = re.search(r"[Ee][Pp]?[\s_\-]?(\d{1,4})", name)
    ep = f"EP{ep_match.group(1).zfill(2)}" if ep_match else None

    # Extract quality
    quality = None
    if re.search(r"4[Kk]|2160[Pp]?", name):
        quality = "4K"
    elif re.search(r"1080[Pp]?", name):
        quality = "1080p"
    elif re.search(r"720[Pp]?", name):
        quality = "720p"

    # Clean title
    title = re.sub(r"[_\-\.]", " ", name)
    title = re.sub(r"\s*[Ee][Pp]?[\s_\-]?\d{1,4}", "", title)
    title = re.sub(r"(4[Kk]|2160p?|1080p?|720p?|x264|x265|HEVC|BluRay|WEB|DL|HDR|SDR)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s{2,}", " ", title).strip()

    parts = [title]
    if ep:
        parts.append(ep)
    if quality:
        parts.append(quality)

    return " | ".join(parts)
