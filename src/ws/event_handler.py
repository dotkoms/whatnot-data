"""
Maps confirmed Whatnot Phoenix channel events to Discord bot calls.

Confirmed topics (from live traffic):
  auction:<stream_id>   — bid_placed, giveaway_entry_count_updated, etc.
  commerce:<stream_id>  — auction_ended, payment_succeeded

Confirmed sold price flow:
  1. commerce -> auction_ended   (soldPriceCents may be null, use highestBid.priceCents)
  2. commerce -> payment_succeeded (soldPriceCents confirmed, purchaserUserId populated)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AuctionEventHandler:
    def __init__(self, bot, stream_url: str, seller: str):
        self.bot = bot
        self.stream_url = stream_url
        self.seller = seller
        self._current_card: Optional[str] = None
        self._current_image_key: Optional[str] = None

    async def handle(self, topic: str, event: str, payload: dict):
        logger.info(f"[EVENT] topic={topic} event={event}")

        if event == "bid_placed":
            await self._on_bid(payload)
        elif event == "auction_ended":
            await self._on_auction_ended(payload)
        elif event == "payment_succeeded":
            await self._on_payment_succeeded(payload)
        elif event in ("auction_started", "item_listed", "product_listed"):
            await self._on_auction_start(payload)
        else:
            logger.debug(f"Unhandled event: {event}")

    async def _on_auction_start(self, payload: dict):
        product = payload.get("product", payload)
        self._current_card = product.get("name")
        media = product.get("media") or []
        self._current_image_key = media[0].get("key") if media else None
        starting_bid = (product.get("auctionMinimumCents") or 0) / 100
        await self.bot.post_auction_start(
            card_name=self._current_card,
            starting_bid=starting_bid,
            seller=self.seller,
        )

    async def _on_bid(self, payload: dict):
        amount = (payload.get("priceCents") or payload.get("amount") or 0) / 100
        user = payload.get("user") or {}
        username = user.get("username") or payload.get("userId") or "unknown"
        await self.bot.post_bid(
            amount=amount,
            username=username,
            card_name=self._current_card,
        )

    async def _on_auction_ended(self, payload: dict):
        product = payload.get("product", {})
        self._current_card = product.get("name", self._current_card)
        media = product.get("media") or []
        self._current_image_key = media[0].get("key") if media else self._current_image_key

        highest_bid = product.get("highestBid") or {}
        price_cents = product.get("soldPriceCents") or highest_bid.get("priceCents") or 0
        final_price = price_cents / 100

        buyer = (product.get("purchaserUser") or highest_bid.get("user") or {})
        buyer_username = buyer.get("username", "unknown")
        bid_count = product.get("bidCount", 0)

        await self.bot.post_sold(
            card_name=self._current_card,
            final_price=final_price,
            seller=self.seller,
            stream_url=self.stream_url,
            buyer=buyer_username,
            bid_count=bid_count,
            image_key=self._current_image_key,
        )
        self._current_card = None
        self._current_image_key = None

    async def _on_payment_succeeded(self, payload: dict):
        product = payload.get("product", {})
        sold_cents = product.get("soldPriceCents") or 0
        if sold_cents == 0:
            return
        card_name = product.get("name", "Unknown card")
        buyer = (product.get("purchaserUser") or {})
        buyer_username = buyer.get("username", "unknown")
        logger.info(f"[PAYMENT CONFIRMED] {card_name} -> ${sold_cents/100:.2f} by {buyer_username}")
