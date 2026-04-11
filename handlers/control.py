from __future__ import annotations
from telethon import Button, events

from utils.access import is_authorized
from utils.cancel import cancel
from utils.state import JobState

async def _start_text(event):
    await event.reply(
        "Send /mux to start.\n"
        "You can send subtitle later, download subtitle online, or skip it.",
        buttons=[[Button.inline("✖️ CANCEL ✖️", data=b"cancel")]],
    )

async def _cancel(event, state_store: dict[int, JobState]):
    if not is_authorized(event.sender_id):
        return
    cancel(event.sender_id)
    st = state_store.get(event.sender_id)
    if st:
        st.cancel_requested = True
        st.stage = "idle"
    await event.answer("Cancelled")

async def register_control_handlers(client, state_store: dict[int, JobState]):
    @client.on(events.NewMessage(pattern=r"^/start$"))
    async def _(event):
        if not is_authorized(event.sender_id):
            return
        await _start_text(event)

    @client.on(events.NewMessage(pattern=r"^/cancel$"))
    async def _(event):
        await _cancel(event, state_store)

    @client.on(events.CallbackQuery(data=b"cancel"))
    async def _(event):
        await _cancel(event, state_store)
