import os
from pyrogram import Client

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_string = os.getenv("SESSION_STRING")

app = Client("thefrictionrealmbot", api_id=api_id, api_hash=api_hash, session_string=session_string)



app.run()
