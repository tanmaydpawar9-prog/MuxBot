"""
Per-user state machine.
States per flow:

MUX FLOW:
  mux_await_video      -> waiting for video
  mux_await_sub        -> waiting for .ass subtitle
  mux_await_thumb      -> waiting for thumbnail or /skip
  mux_await_filename   -> waiting for custom filename

STYLE FLOW:
  style_await_sub      -> waiting for .srt/.ass
  style_await_mode     -> waiting for button (cinematic/full4k)

CONVERT FLOW:
  convert_await_sub    -> waiting for .srt/.ass
"""

import asyncio

# user_id -> dict
_state: dict[int, dict] = {}
# msg_id -> asyncio.Event (cancel)
_cancel_flags: dict[int, asyncio.Event] = {}
# user_id -> set of msg_ids
_user_tasks: dict[int, set[int]] = {}


def get_state(user_id: int) -> dict:
    return _state.get(user_id, {})


def set_state(user_id: int, **kwargs):
    if user_id not in _state:
        _state[user_id] = {}
    _state[user_id].update(kwargs)


def clear_state(user_id: int):
    _state.pop(user_id, None)


def get_cancel_flag(user_id: int, msg_id: int) -> asyncio.Event:
    if msg_id not in _cancel_flags:
        _cancel_flags[msg_id] = asyncio.Event()
    if user_id not in _user_tasks:
        _user_tasks[user_id] = set()
    _user_tasks[user_id].add(msg_id)
    return _cancel_flags[msg_id]

def clear_cancel_flag(user_id: int, msg_id: int):
    _cancel_flags.pop(msg_id, None)
    if user_id in _user_tasks and msg_id in _user_tasks[user_id]:
        _user_tasks[user_id].remove(msg_id)

def cancel_msg(msg_id: int):
    if msg_id in _cancel_flags:
        _cancel_flags[msg_id].set()


def cancel_user(user_id: int):
    for msg_id in list(_user_tasks.get(user_id, [])):
        cancel_msg(msg_id)
