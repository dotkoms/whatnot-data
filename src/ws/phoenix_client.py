"""
Phoenix WebSocket client for Whatnot.

Confirmed endpoints (from live traffic):
  wss://www.whatnot.com/services/auction/socket/websocket
  wss://www.whatnot.com/services/live/socket/websocket

Confirmed topics:
  auction:<stream_id>   — bid_placed, reactions, view counts
  commerce:<stream_id>  — auction_ended, payment_succeeded  ← sold price lives here

Phoenix wire protocol: [join_ref, ref, topic, event, payload]
"""

import asyncio
import json
import logging
from typing import Callable, Optional

import websockets

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30
AUCTION_WS_URL = "wss://www.whatnot.com/services/auction/socket/websocket"


class PhoenixClient:
    def __init__(
        self,
        stream_id: str,
        auth_token: Optional[str] = None,
        on_event: Optional[Callable] = None,
        ws_url: str = AUCTION_WS_URL,
    ):
        self.stream_id = stream_id
        self.auth_token = auth_token
        self.on_event = on_event
        self.ws_url = ws_url
        self.topics = [
            f"auction:{stream_id}",
            f"commerce:{stream_id}",
        ]
        self._ref = 0
        self._running = False
        self._ws = None

    def _next_ref(self) -> str:
        self._ref += 1
        return str(self._ref)

    def _msg(self, join_ref, ref, topic, event, payload) -> str:
        return json.dumps([join_ref, ref, topic, event, payload])

    async def _send(self, join_ref, ref, topic, event, payload):
        msg = self._msg(join_ref, ref, topic, event, payload)
        logger.debug(f"[SEND] {msg}")
        await self._ws.send(msg)

    async def _join_topics(self):
        for i, topic in enumerate(self.topics):
            join_ref = str(i + 1)
            payload = {"token": self.auth_token} if self.auth_token else {}
            await self._send(join_ref, self._next_ref(), topic, "phx_join", payload)
            logger.info(f"Joined: {topic}")

    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if self._running:
                await self._send(None, self._next_ref(), "phoenix", "heartbeat", {})

    async def _listen(self):
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
                await self._handle(msg)
            except Exception as e:
                logger.error(f"Parse error: {e} | raw: {raw}")

    async def _handle(self, msg):
        if not isinstance(msg, list) or len(msg) < 5:
            return
        join_ref, ref, topic, event, payload = msg
        if event == "phx_reply":
            logger.debug(f"phx_reply [{topic}] status={payload.get('status')}")
            return
        if event == "phx_error":
            logger.error(f"phx_error [{topic}] {payload}")
            return
        if self.on_event:
            await self.on_event(topic=topic, event=event, payload=payload)

    async def connect(self):
        url = self.ws_url
        params = "vsn=2.0.0"
        if self.auth_token:
            params += f"&token={self.auth_token}"
        url = f"{url}?{params}"

        self._running = True
        logger.info(f"Connecting to {url}")

        async with websockets.connect(url) as ws:
            self._ws = ws
            await self._join_topics()
            await asyncio.gather(
                self._heartbeat_loop(),
                self._listen(),
            )

    def stop(self):
        self._running = False
