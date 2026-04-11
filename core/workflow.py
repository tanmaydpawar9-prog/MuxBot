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
# user_id -> asyncio.Event (cancel)
_cancel_flags: dict[int, asyncio.Event] = {}


def get_state(user_id: int) -> dict:
    return _state.get(user_id, {})


def set_state(user_id: int, **kwargs):
    if user_id not in _state:
        _state[user_id] = {}
    _state[user_id].update(kwargs)


def clear_state(user_id: int):
    _state.pop(user_id, None)


def get_cancel_flag(user_id: int) -> asyncio.Event:
    if user_id not in _cancel_flags:
        _cancel_flags[user_id] = asyncio.Event()
    return _cancel_flags[user_id]


def reset_cancel_flag(user_id: int):
    _cancel_flags[user_id] = asyncio.Event()


def cancel_user(user_id: int):
    flag = get_cancel_flag(user_id)
    flag.set()
