"""
Entry point: single stream monitor → card identification → SQLite.

Usage:
    python3 main.py <whatnot_stream_url> <seller_name>

Example:
    python3 main.py https://www.whatnot.com/live/abc123 SomeSellerName

Requires:
    - data/session/ Firefox session (run scripts/intercept_ws.py once to log in)
    - data/cards.db  (run scripts/build_card_db.py first)
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from src.vision.card_db import init_db
from src.vision.frame_extractor import FrameExtractor
from src.vision.hls_interceptor import HLSInterceptor
from src.ws.event_handler import AuctionEventHandler
from src.ws.phoenix_client import PhoenixClient

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SESSION_DIR = str(Path(__file__).parent / "data" / "session")
LOGIN_URL = "https://www.whatnot.com/login"


def _parse_stream_id(stream_url: str) -> str:
    return stream_url.rstrip("/").split("/")[-1]


async def _ensure_logged_in(page):
    if "login" in page.url or "verify" in page.url or page.url == "about:blank":
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

    if "login" in page.url or "verify" in page.url:
        logger.warning("Not logged in — log in manually in the browser window (including SMS code).")
        while "login" in page.url or "verify" in page.url or "confirm" in page.url:
            await asyncio.sleep(1)
        logger.info(f"Logged in. URL: {page.url}")


async def run(stream_url: str, seller: str):
    stream_id = _parse_stream_id(stream_url)
    logger.info(f"Stream ID: {stream_id}")

    init_db()

    handler = AuctionEventHandler(
        stream_url=stream_url,
        seller=seller,
        stream_id=stream_id,
    )

    extractor = FrameExtractor(stream_id=stream_id, interval=30)
    hls_interceptor = HLSInterceptor()

    async def on_frame(frame_path: str, ts: int):
        handler.set_last_frame(frame_path)

    async def browser_task():
        async with async_playwright() as p:
            os.makedirs(SESSION_DIR, exist_ok=True)
            context = await p.firefox.launch_persistent_context(
                SESSION_DIR,
                headless=False,
            )
            page = context.pages[0] if context.pages else await context.new_page()

            await _ensure_logged_in(page)

            hls_interceptor.attach(page)

            logger.info(f"Navigating to {stream_url}")
            await page.goto(stream_url, wait_until="domcontentloaded", timeout=60000)
            logger.info("Stream page loaded — waiting for HLS URL...")

            hls_url = await hls_interceptor.wait_for_url(timeout=20.0)

            if hls_url:
                logger.info(f"HLS URL found: {hls_url}")
                await extractor.start_hls(hls_url, on_frame=on_frame)
            else:
                logger.warning("No HLS URL — Agora stream detected, using browser screenshots")
                await extractor.start_screenshot(page, on_frame=on_frame)

            await context.close()

    async def ws_task():
        client = PhoenixClient(
            stream_id=stream_id,
            auth_token=os.environ.get("WHATNOT_AUTH_TOKEN"),
            on_event=handler.handle,
        )
        await client.connect()

    await asyncio.gather(
        ws_task(),
        browser_task(),
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 main.py <stream_url> <seller_name>")
        print("Example: python3 main.py https://www.whatnot.com/live/abc123 SellerName")
        sys.exit(1)

    asyncio.run(run(sys.argv[1], sys.argv[2]))
