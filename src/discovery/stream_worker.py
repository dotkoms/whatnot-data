"""
StreamWorker — one self-contained monitor per Whatnot stream.

One browser tab per stream (shared browser context).
Self-terminates when stream ends or WS closes.
"""

import asyncio
import logging
import os
from typing import Optional

from src.vision.frame_extractor import FrameExtractor
from src.vision.hash_index import HashIndex
from src.vision.hls_interceptor import HLSInterceptor
from src.ws.event_handler import AuctionEventHandler
from src.ws.phoenix_client import PhoenixClient

logger = logging.getLogger(__name__)


class StreamWorker:
    def __init__(
        self,
        stream_id: str,
        seller: str,
        browser_context,
        hash_index: HashIndex,
        auth_token: Optional[str] = None,
        on_token_expired=None,
    ):
        self.stream_id = stream_id
        self.seller = seller
        self.stream_url = f"https://www.whatnot.com/live/{stream_id}"
        self.auth_token = auth_token
        self._on_token_expired = on_token_expired
        self._context = browser_context
        self._hash_index = hash_index
        self._page = None
        self._running = False
        self._done = asyncio.Event()
        self._browser_task: Optional[asyncio.Task] = None

    async def run(self):
        self._running = True
        logger.info(f"[{self.stream_id}] Worker starting")

        handler = AuctionEventHandler(
            stream_url=self.stream_url,
            seller=self.seller,
            stream_id=self.stream_id,
            hash_index=self._hash_index,
        )

        extractor = FrameExtractor(stream_id=self.stream_id, interval=30)
        hls_interceptor = HLSInterceptor()

        async def on_frame(frame_path: str, ts: int):
            handler.set_last_frame(frame_path)

        async def on_stream_end(stream_id: str):
            logger.info(f"[{stream_id}] Stream ended — shutting down worker")
            self._running = False
            extractor.stop()
            if self._browser_task and not self._browser_task.done():
                self._browser_task.cancel()
            self._done.set()

        client = PhoenixClient(
            stream_id=self.stream_id,
            auth_token=self.auth_token,
            on_event=handler.handle,
            on_stream_end=on_stream_end,
            on_token_expired=self._on_token_expired,
        )

        async def browser_task():
            try:
                self._page = await self._context.new_page()
                hls_interceptor.attach(self._page)

                await self._page.goto(self.stream_url, wait_until="domcontentloaded", timeout=60000)
                logger.info(f"[{self.stream_id}] Page loaded")

                hls_url = await hls_interceptor.wait_for_url(timeout=20.0)

                if hls_url:
                    logger.info(f"[{self.stream_id}] HLS stream detected")
                    await extractor.start_hls(hls_url, on_frame=on_frame)
                else:
                    logger.info(f"[{self.stream_id}] Agora stream — using screenshots")
                    await extractor.start_screenshot(self._page, on_frame=on_frame)
            except Exception as e:
                logger.error(f"[{self.stream_id}] Browser task error: {e}")
            finally:
                if self._page and not self._page.is_closed():
                    await self._page.close()

        try:
            self._browser_task = asyncio.ensure_future(browser_task())
            await asyncio.gather(
                client.connect(),
                self._browser_task,
            )
        except Exception as e:
            logger.error(f"[{self.stream_id}] Worker error: {e}")
        finally:
            self._running = False
            self._done.set()
            logger.info(f"[{self.stream_id}] Worker stopped")

    async def stop(self):
        self._running = False
        if self._page and not self._page.is_closed():
            await self._page.close()
        self._done.set()

    async def wait_until_done(self):
        await self._done.wait()

    @property
    def is_running(self):
        return self._running
