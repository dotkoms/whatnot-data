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
import base64
import json
import logging
import time
from typing import Callable, Optional

import websockets

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30
AUCTION_WS_URL = "wss://www.whatnot.com/services/auction/socket/websocket"
LIVE_WS_URL = "wss://www.whatnot.com/services/live/socket/websocket"
RECONNECT_DELAY = 5
MAX_RECONNECT_ATTEMPTS = 10


def _jwt_expiry(token: str) -> Optional[int]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.b64decode(payload))
        return data.get("exp")
    except Exception:
        return None


class PhoenixClient:
    def __init__(
        self,
        stream_id: str,
        auth_token: Optional[str] = None,
        on_event: Optional[Callable] = None,
        on_stream_end: Optional[Callable] = None,
        on_token_expired: Optional[Callable] = None,
    ):
        self.stream_id = stream_id
        self.auth_token = auth_token
        self.on_event = on_event
        self.on_stream_end = on_stream_end
        self.on_token_expired = on_token_expired
        self._ref = 0
        self._running = False
        self._token_expired = False
        self._stream_end_fired = False

        if auth_token:
            exp = _jwt_expiry(auth_token)
            if exp:
                expires_in = exp - int(time.time())
                if expires_in <= 0:
                    logger.warning("WHATNOT_AUTH_TOKEN is already expired — run scripts/intercept_ws.py to refresh")
                else:
                    import datetime
                    exp_str = datetime.datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M:%S")
                    logger.info(f"Auth token expires at {exp_str} ({expires_in // 3600}h {(expires_in % 3600) // 60}m remaining)")

    def _next_ref(self) -> str:
        self._ref += 1
        return str(self._ref)

    async def _send(self, ws, join_ref, ref, topic, event, payload):
        msg = json.dumps([join_ref, ref, topic, event, payload])
        logger.debug(f"[SEND] {msg}")
        await ws.send(msg)

    async def _join_topics(self, ws, topics: list[str]):
        for i, topic in enumerate(topics):
            join_ref = str(i + 1)
            payload = {"token": self.auth_token} if self.auth_token else {}
            await self._send(ws, join_ref, self._next_ref(), topic, "phx_join", payload)
            logger.info(f"Joined: {topic}")

    async def _heartbeat_loop(self, ws):
        while self._running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if self._running:
                try:
                    await self._send(ws, None, self._next_ref(), "phoenix", "heartbeat", {})
                except Exception:
                    break

    async def _listen(self, ws):
        async for raw in ws:
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
            if status == "error" and not self._token_expired:
                self._token_expired = True
                logger.warning(f"Join rejected for {topic} — auth token expired or invalid. Run scripts/intercept_ws.py to refresh.")
                if self.on_token_expired:
                    await self.on_token_expired()
            return
        if event == "phx_error":
            logger.error(f"phx_error [{topic}] {payload}")
            return
        if event == "phx_close":
            logger.info(f"Stream ended: {topic}")
            self._running = False
            if self.on_stream_end and not self._stream_end_fired:
                self._stream_end_fired = True
                await self.on_stream_end(self.stream_id)
            return
        if self.on_event:
            await self.on_event(topic=topic, event=event, payload=payload)

    async def _connect_socket(self, ws_url: str, topics: list[str]):
        url = f"{ws_url}?vsn=2.0.0"
        if self.auth_token:
            url += f"&token={self.auth_token}"

        attempts = 0
        while self._running and attempts < MAX_RECONNECT_ATTEMPTS:
            try:
                logger.info(f"Connecting to {ws_url} (attempt {attempts + 1})")
                async with websockets.connect(url) as ws:
                    attempts = 0
                    await self._join_topics(ws, topics)
                    await asyncio.gather(
                        self._heartbeat_loop(ws),
                        self._listen(ws),
                    )
            except websockets.ConnectionClosedOK:
                logger.info(f"WS closed cleanly [{ws_url}] stream={self.stream_id}")
                return
            except (websockets.ConnectionClosedError, OSError) as e:
                attempts += 1
                if attempts >= MAX_RECONNECT_ATTEMPTS:
                    logger.error(f"Max reconnect attempts reached [{ws_url}] stream={self.stream_id}")
                    return
                delay = RECONNECT_DELAY * attempts
                logger.warning(f"WS disconnected ({e}) — reconnecting in {delay}s (attempt {attempts}/{MAX_RECONNECT_ATTEMPTS})")
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error(f"Unexpected WS error [{ws_url}]: {e}")
                attempts += 1
                await asyncio.sleep(RECONNECT_DELAY)

    async def connect(self):
        self._running = True
        self._stream_end_fired = False
        await asyncio.gather(
            self._connect_socket(
                AUCTION_WS_URL,
                [f"auction:{self.stream_id}", f"commerce:{self.stream_id}"],
            ),
            self._connect_socket(
                LIVE_WS_URL,
                [f"live:{self.stream_id}"],
            ),
        )
        self._running = False
        if self.on_stream_end and not self._stream_end_fired:
            self._stream_end_fired = True
            await self.on_stream_end(self.stream_id)

    def stop(self):
        self._running = False
