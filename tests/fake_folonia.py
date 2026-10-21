"""Un faux service Folonia : appariement, déliement, et la passerelle de la liaison.

Il se comporte comme le service Folonia : secret exigé avant la montée en WebSocket, `hello` puis
`welcome`, requêtes `list` et `read`, fermetures 4000 à 4003.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

SECRET = "fol_" + "A" * 43
CODE = "K7QM4XT2"
LINK_ID = "6f9c1d2e-0a4b-4c5d-8e7f-001122334455"


class FakeFolonia:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {CODE: LINK_ID}
        self.secrets: dict[str, str] = {}
        #: Messages reçus de la maison, dans l'ordre (hello, réponses, bye).
        self.received: list[dict[str, Any]] = []
        self.unlinked: list[str] = []
        self.paired_with: list[dict[str, Any]] = []
        self.connected = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.ws: web.WebSocketResponse | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._next = 0
        app = web.Application()
        app.router.add_post("/v1/home/pair", self._pair)
        app.router.add_delete("/v1/home/link", self._unlink)
        app.router.add_get("/v1/home/link", self._link)
        self.server = TestServer(app, host="127.0.0.1")

    async def start(self) -> str:
        await self.server.start_server()
        return str(self.server.make_url("")).rstrip("/")

    async def stop(self) -> None:
        await self.server.close()

    def link_secret(self) -> str:
        """Un secret déjà apparié, pour les tests qui commencent relié."""
        self.secrets[SECRET] = LINK_ID
        return SECRET

    async def _pair(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.paired_with.append(body)
        link = self.codes.pop(body.get("code"), None)
        if link is None:
            return web.json_response({"error": {"code": "invalid_request"}}, status=400)
        self.secrets[SECRET] = link
        return web.json_response({"link_id": link, "link_secret": SECRET}, status=201)

    async def _unlink(self, request: web.Request) -> web.Response:
        secret = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if self.secrets.pop(secret, None) is None:
            return web.Response(status=401)
        self.unlinked.append(secret)
        return web.Response(status=204)

    async def _link(self, request: web.Request) -> web.StreamResponse:
        secret = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if secret not in self.secrets:
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        hello = await ws.receive_json(timeout=5)
        self.received.append(hello)
        await ws.send_json({"type": "welcome", "protocol": 1})
        self.ws = ws
        self.disconnected.clear()
        self.connected.set()
        async for message in ws:
            if message.type != WSMsgType.TEXT:
                continue
            data = json.loads(message.data)
            self.received.append(data)
            if data.get("type") == "response":
                future = self._pending.pop(data.get("id"), None)
                if future is not None and not future.done():
                    future.set_result(data)
        self.ws = None
        self.connected.clear()
        self.disconnected.set()
        return ws

    async def request(self, op: str, **extra: Any) -> dict[str, Any]:
        """Une requête à la maison, comme la passerelle en envoie pendant un appel."""
        assert self.ws is not None, "aucune liaison ouverte"
        self._next += 1
        request_id = str(self._next)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self.ws.send_json({"type": "request", "id": request_id, "op": op, **extra})
        return await asyncio.wait_for(future, 5)

    async def close_link(self, code: int) -> None:
        assert self.ws is not None
        await self.ws.close(code=code)
