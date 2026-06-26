"""
Entry point for Phase 1: single stream monitor → Discord bot.

Usage:
    python main.py <whatnot_stream_url> <seller_name> <phoenix_topic>

Example (topic format TBD — run scripts/intercept_ws.py first):
    python main.py https://www.whatnot.com/live/abc123 SomeSellerName livestream:abc123
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from src.discord.bot import AuctionBot
from src.ws.event_handler import AuctionEventHandler
from src.ws.phoenix_client import PhoenixClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def run(stream_url: str, seller: str, topic: str):
    bot = AuctionBot()
    handler = AuctionEventHandler(bot=bot, stream_url=stream_url, seller=seller)

    ws_url = os.environ.get("WHATNOT_WS_URL", "wss://live-service.whatnot.com/socket/websocket")
    auth_token = os.environ.get("WHATNOT_AUTH_TOKEN")

    client = PhoenixClient(
        ws_url=ws_url,
        topic=topic,
        auth_token=auth_token,
        on_event=handler.handle,
    )

    await bot.post_stream_live(seller=seller, stream_url=stream_url)

    async def start_bot():
        await bot.start(os.environ["DISCORD_BOT_TOKEN"])

    await asyncio.gather(
        start_bot(),
        client.connect(),
    )


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python main.py <stream_url> <seller_name> <phoenix_topic>")
        print("Run scripts/intercept_ws.py first to discover the topic format.")
        sys.exit(1)

    stream_url, seller, topic = sys.argv[1], sys.argv[2], sys.argv[3]
    asyncio.run(run(stream_url, seller, topic))
