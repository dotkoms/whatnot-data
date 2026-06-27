"""
Maps confirmed Whatnot Phoenix channel events to console output + SQLite.

Confirmed topics (from live traffic):
  auction:<stream_id>   — bid_placed, giveaway_entry_count_updated, etc.
  commerce:<stream_id>  — auction_ended, payment_succeeded

Confirmed sold price flow:
  1. commerce -> auction_ended   (soldPriceCents may be null, use highestBid.priceCents)
  2. commerce -> payment_succeeded (soldPriceCents confirmed, purchaserUserId populated)
"""

import logging
import time
from typing import Optional

from src.vision.card_db import save_auction_result
from src.vision.hash_index import HashIndex, get_index
from src.vision.card_identifier import CardIdentifier

logger = logging.getLogger(__name__)


class AuctionEventHandler:
    def __init__(
        self,
        stream_url: str,
        seller: str,
        stream_id: str = "",
        hash_index: Optional[HashIndex] = None,
    ):
        self.stream_url = stream_url
        self.seller = seller
        self.stream_id = stream_id
        self._index = hash_index or get_index()
        self._identifier = CardIdentifier(hash_index=self._index)
        self._current_card: Optional[str] = None
        self._current_image_key: Optional[str] = None
        self._current_listing_id: Optional[str] = None
        self._last_frame_path: Optional[str] = None

    def set_last_frame(self, frame_path: str):
        self._last_frame_path = frame_path

    async def handle(self, topic: str, event: str, payload: dict):
        logger.info(f"[{self.stream_id}] topic={topic} event={event}")

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
        self._current_listing_id = product.get("listingId") or product.get("id")
        starting_bid = (product.get("auctionMinimumCents") or 0) / 100
        logger.info(f"[{self.stream_id}] AUCTION START — {self._current_card} starting at ${starting_bid:.2f}")

    async def _on_bid(self, payload: dict):
        amount = (payload.get("priceCents") or payload.get("amount") or 0) / 100
        user = payload.get("user") or {}
        username = user.get("username") or payload.get("userId") or "unknown"
        logger.info(f"[{self.stream_id}] BID — ${amount:.2f} by {username} on {self._current_card}")

    async def _on_auction_ended(self, payload: dict):
        product = payload.get("product", {})
        self._current_card = product.get("name", self._current_card)
        media = product.get("media") or []
        self._current_image_key = media[0].get("key") if media else self._current_image_key
        listing_id = product.get("listingId") or product.get("id") or self._current_listing_id

        highest_bid = product.get("highestBid") or {}
        price_cents = product.get("soldPriceCents") or highest_bid.get("priceCents") or 0
        final_price = price_cents / 100

        buyer = (product.get("purchaserUser") or highest_bid.get("user") or {})
        buyer_username = buyer.get("username", "unknown")
        bid_count = product.get("bidCount", 0)

        card_info = await self._identifier.identify(
            frame_path=self._last_frame_path,
            whatnot_image_key=self._current_image_key,
        )

        identified_name = (card_info or {}).get("name") or self._current_card
        card_id = (card_info or {}).get("card_id")
        confidence = (card_info or {}).get("confidence", 0.0)
        method = (card_info or {}).get("method", "none")
        frame_path = (card_info or {}).get("crop_path") or self._last_frame_path

        logger.info(
            f"[{self.stream_id}] SOLD — {identified_name} "
            f"${final_price:.2f} | buyer={buyer_username} bids={bid_count} "
            f"method={method} confidence={confidence:.2f}"
        )

        try:
            save_auction_result(
                stream_id=self.stream_id,
                listing_id=listing_id or "",
                card_id=card_id,
                card_name=identified_name or "",
                sold_price_cents=price_cents,
                buyer_username=buyer_username,
                bid_count=bid_count,
                seller_user_id=self.seller,
                image_key=self._current_image_key,
                confidence=confidence,
                frame_path=frame_path,
                ended_at=int(time.time()),
            )
        except Exception as e:
            logger.error(f"[{self.stream_id}] Failed to save auction result: {e}")

        self._current_card = None
        self._current_image_key = None
        self._current_listing_id = None

    async def _on_payment_succeeded(self, payload: dict):
        product = payload.get("product", {})
        sold_cents = product.get("soldPriceCents") or 0
        if sold_cents == 0:
            return
        card_name = product.get("name", "Unknown card")
        buyer = (product.get("purchaserUser") or {})
        buyer_username = buyer.get("username", "unknown")
        logger.info(f"[{self.stream_id}] PAYMENT CONFIRMED — {card_name} ${sold_cents/100:.2f} by {buyer_username}")
