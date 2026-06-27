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
RECONNECT_DELAY = 5
MAX_RECONNECT_ATTEMPTS = 10


class PhoenixClient:
    def __init__(
        self,
        stream_id: str,
        auth_token: Optional[str] = None,
        on_event: Optional[Callable] = None,
        on_stream_end: Optional[Callable] = None,
        ws_url: str = AUCTION_WS_URL,
    ):
        self.stream_id = stream_id
        self.auth_token = auth_token
        self.on_event = on_event
        self.on_stream_end = on_stream_end
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
            if self._running and self._ws:
                try:
                    await self._send(None, self._next_ref(), "phoenix", "heartbeat", {})
                except Exception:
                    break

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
            status = payload.get("status")
            logger.debug(f"phx_reply [{topic}] status={status}")
            if status == "error":
                logger.warning(f"Join rejected for {topic} — check auth token")
            return
        if event == "phx_error":
            logger.error(f"phx_error [{topic}] {payload}")
            return
        if event == "phx_close":
            logger.info(f"Stream ended: {topic}")
            self._running = False
            if self.on_stream_end:
                await self.on_stream_end(self.stream_id)
            return
        if self.on_event:
            await self.on_event(topic=topic, event=event, payload=payload)

    async def connect(self):
        url = f"{self.ws_url}?vsn=2.0.0"
        if self.auth_token:
            url += f"&token={self.auth_token}"

        self._running = True
        attempts = 0

        while self._running and attempts < MAX_RECONNECT_ATTEMPTS:
            try:
                logger.info(f"Connecting to {self.ws_url} (attempt {attempts + 1})")
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    attempts = 0
                    await self._join_topics()
                    await asyncio.gather(
                        self._heartbeat_loop(),
                        self._listen(),
                    )
            except websockets.ConnectionClosedOK:
                logger.info(f"WS closed cleanly for stream {self.stream_id}")
                self._running = False
                if self.on_stream_end:
                    await self.on_stream_end(self.stream_id)
                return
            except (websockets.ConnectionClosedError, OSError) as e:
                attempts += 1
                if attempts >= MAX_RECONNECT_ATTEMPTS:
                    logger.error(f"Max reconnect attempts reached for {self.stream_id}")
                    self._running = False
                    if self.on_stream_end:
                        await self.on_stream_end(self.stream_id)
                    return
                delay = RECONNECT_DELAY * attempts
                logger.warning(f"WS disconnected ({e}) — reconnecting in {delay}s (attempt {attempts}/{MAX_RECONNECT_ATTEMPTS})")
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error(f"Unexpected WS error: {e}")
                attempts += 1
                await asyncio.sleep(RECONNECT_DELAY)

    def stop(self):
        self._running = False
