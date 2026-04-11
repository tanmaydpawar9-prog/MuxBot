from dataclasses import dataclass, field
from typing import Optional

@dataclass
class JobState:
    stage: str = "idle"
    video_path: Optional[str] = None
    subtitle_path: Optional[str] = None
    output_name: Optional[str] = None
    thumb_path: Optional[str] = None
    subtitle_mode: str = "pending"   # pending | upload | online | skip
    subtitle_url: Optional[str] = None
    message_chat_id: Optional[int] = None
    message_id: Optional[int] = None
    cancel_requested: bool = False
    task_id: Optional[str] = None
