import logging
import os

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

IMAGE_BASE = "https://images.whatnot.com/"


class AuctionBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.channel_id = int(os.environ["DISCORD_CHANNEL_ID"])
        self._channel = None

    async def on_ready(self):
        self._channel = self.get_channel(self.channel_id)
        logger.info(f"Logged in as {self.user} | Channel: {self._channel}")

    async def send(self, message: str):
        if self._channel is None:
            self._channel = self.get_channel(self.channel_id)
        if self._channel:
            await self._channel.send(message)
        else:
            logger.error(f"Channel {self.channel_id} not found")

    async def post_stream_live(self, seller: str, stream_url: str):
        await self.send(f"🟢 **Stream live** | {seller} | {stream_url}")

    async def post_auction_start(self, card_name: str, starting_bid: float, seller: str):
        name = card_name or "Unknown card"
        await self.send(
            f"📦 **Auction started** | {name} | Starting bid: **${starting_bid:.2f}** | Seller: {seller}"
        )

    async def post_bid(self, amount: float, username: str, card_name: str = None):
        name = f" on {card_name}" if card_name else ""
        await self.send(f"💰 **Bid{name}** | **${amount:.2f}** by {username}")

    async def post_sold(
        self,
        card_name: str,
        final_price: float,
        seller: str,
        stream_url: str,
        buyer: str = "unknown",
        bid_count: int = 0,
        image_key: str = None,
    ):
        name = card_name or "Unknown card"
        image_url = f"{IMAGE_BASE}{image_key}" if image_key else ""
        msg = (
            f"🔨 **SOLD** | {name}\n"
            f"💵 **${final_price:.2f}** | Buyer: **{buyer}** | Bids: {bid_count}\n"
            f"Seller: {seller} | {stream_url}"
        )
        if image_url:
            msg += f"\n{image_url}"
        await self.send(msg)
