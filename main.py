"""
Entry point for Phase 1: single stream monitor → Discord bot.

Usage:
    python main.py <whatnot_stream_url> <seller_name>

Example:
    python main.py https://www.whatnot.com/live/abc123 SomeSellerName

The stream_id is parsed from the URL automatically.
Run scripts/intercept_ws.py first to verify WS connectivity.
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from src.discord.bot import AuctionBot
from src.vision.card_db import init_db
from src.vision.frame_extractor import FrameExtractor
from src.vision.hls_interceptor import HLSInterceptor
from src.ws.event_handler import AuctionEventHandler
from src.ws.phoenix_client import PhoenixClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _parse_stream_id(stream_url: str) -> str:
    return stream_url.rstrip("/").split("/")[-1]


async def run(stream_url: str, seller: str):
    stream_id = _parse_stream_id(stream_url)
    logger.info(f"Stream ID: {stream_id}")

    init_db()

    bot = AuctionBot()
    handler = AuctionEventHandler(
        bot=bot,
        stream_url=stream_url,
        seller=seller,
        stream_id=stream_id,
    )

    extractor = FrameExtractor(stream_id=stream_id, interval=30)

    async def on_frame(frame_path: str, ts: int):
        handler.set_last_frame(frame_path)
        logger.debug(f"Frame updated: {frame_path}")

    ws_url = "wss://www.whatnot.com/services/auction/socket/websocket"
    auth_token = os.environ.get("WHATNOT_AUTH_TOKEN")

    client = PhoenixClient(
        ws_url=ws_url,
        stream_id=stream_id,
        auth_token=auth_token,
        on_event=handler.handle,
    )

    hls_interceptor = HLSInterceptor()

    async def start_bot():
        await bot.start(os.environ["DISCORD_BOT_TOKEN"])

    async def start_frames():
        hls_url = await hls_interceptor.wait_for_url(timeout=60.0)
        if hls_url:
            logger.info(f"HLS URL found: {hls_url}")
            await extractor.start_hls(hls_url, on_frame=on_frame)
        else:
            logger.warning("No HLS URL detected — frame extraction disabled")

    await bot.post_stream_live(seller=seller, stream_url=stream_url)

    await asyncio.gather(
        start_bot(),
        client.connect(),
        start_frames(),
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python main.py <stream_url> <seller_name>")
        sys.exit(1)

    stream_url, seller = sys.argv[1], sys.argv[2]
    asyncio.run(run(stream_url, seller))
