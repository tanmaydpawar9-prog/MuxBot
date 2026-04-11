from typing import Dict, Optional
import asyncio

TASKS: Dict[int, asyncio.Task] = {}

def register(user_id: int, task: asyncio.Task) -> None:
    TASKS[user_id] = task

def cancel(user_id: int) -> bool:
    task = TASKS.get(user_id)
    if task and not task.done():
        task.cancel()
        return True
    return False

def pop(user_id: int) -> None:
    TASKS.pop(user_id, None)
