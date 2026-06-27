"""
Orchestrator — manages all StreamWorkers.

- One shared Firefox browser context (multiple tabs)
- One shared HashIndex (14k cards loaded once)
- Max 20 concurrent streams
- StreamFinder polls every 60s for new/ended streams
- Workers self-terminate when streams end
"""

import asyncio
import logging
import os
from typing import Optional

from src.discovery.stream_finder import StreamFinder
from src.discovery.stream_worker import StreamWorker
from src.vision.hash_index import HashIndex, get_index
from src.vision.card_db import init_db, DB_PATH

logger = logging.getLogger(__name__)

MAX_CONCURRENT_STREAMS = 20


class Orchestrator:
    def __init__(self, browser_context, auth_token: Optional[str] = None):
        self._context = browser_context
        self._auth_token = auth_token
        self._workers: dict[str, StreamWorker] = {}
        self._hash_index = get_index()
        self._finder = StreamFinder(browser_context)

    async def start(self):
        logger.info("Orchestrator starting")

        init_db()

        await asyncio.gather(
            self._finder.poll(
                on_new_stream=self._on_new_stream,
                on_ended_stream=self._on_ended_stream,
            ),
            self._monitor_workers(),
        )

    async def _on_new_stream(self, stream_info: dict):
        stream_id = stream_info["stream_id"]

        if stream_id in self._workers:
            return

        if len(self._workers) >= MAX_CONCURRENT_STREAMS:
            logger.warning(f"Max streams ({MAX_CONCURRENT_STREAMS}) reached — skipping {stream_id}")
            return

        logger.info(f"New stream: {stream_id} | seller={stream_info['seller']} | title={stream_info.get('title')}")

        worker = StreamWorker(
            stream_id=stream_id,
            seller=stream_info.get("seller", "unknown"),
            browser_context=self._context,
            hash_index=self._hash_index,
            auth_token=self._auth_token,
            on_token_expired=self._on_token_expired,
        )
        self._workers[stream_id] = worker

        asyncio.create_task(worker.run())

    async def _on_ended_stream(self, stream_id: str):
        worker = self._workers.get(stream_id)
        if worker:
            await worker.stop()
            del self._workers[stream_id]
            logger.info(f"Removed ended stream: {stream_id} | active={len(self._workers)}")

    async def _monitor_workers(self):
        while True:
            await asyncio.sleep(30)
            dead = [sid for sid, w in self._workers.items() if not w.is_running]
            for sid in dead:
                del self._workers[sid]
                logger.info(f"Cleaned up dead worker: {sid} | active={len(self._workers)}")

            logger.info(f"Active streams: {len(self._workers)}")

    async def _on_token_expired(self):
        logger.error(
            "\n\n⚠️  WHATNOT AUTH TOKEN EXPIRED\n"
            "   All WebSocket joins are being rejected.\n"
            "   Run:  python scripts/intercept_ws.py\n"
            "   Then restart this process.\n"
        )

    async def add_stream(self, stream_id: str, seller: str = "unknown"):
        await self._on_new_stream({"stream_id": stream_id, "seller": seller, "title": ""})
