from __future__ import annotations
import os
import threading
from aiohttp import web
from pathlib import Path

from config import LEECH_DIR, HTTP_PORT

def _app() -> web.Application:
    app = web.Application()

    async def health(request):
        return web.json_response({"status": "ok"})

    async def file_handler(request):
        name = request.match_info["name"]
        path = Path(LEECH_DIR) / name
        if not path.exists():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    app.router.add_get("/", health)
    app.router.add_get("/{name}", file_handler)
    return app

def start_server() -> None:
    Path(LEECH_DIR).mkdir(parents=True, exist_ok=True)
    app = _app()
    from aiohttp import web
import os
from config import LEECH_DIR, HTTP_PORT

async def start_server():
    app = web.Application()

    async def handle(request):
        name = request.match_info['name']
        path = os.path.join(LEECH_DIR, name)

        if not os.path.exists(path):
            raise web.HTTPNotFound()

        return web.FileResponse(path)

    app.router.add_get('/{name}', handle)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", HTTP_PORT)
    await site.start()

    print(f"Leech server running on port {HTTP_PORT}")
