"""
StreamFinder — scrapes active Pokemon card streams from Whatnot.

Polls whatnot.com/explore every 60 seconds.
Filters for Pokemon card streams by category + title keywords.
"""

import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

EXPLORE_URL = "https://www.whatnot.com/explore"
POKEMON_KEYWORDS = ["pokemon", "poke", "tcg", "cards", "charizard", "pikachu", "pack", "booster", "vintage"]
POLL_INTERVAL = 60


class StreamFinder:
    def __init__(self, browser_context):
        self._context = browser_context
        self._known_ids: set[str] = set()

    async def get_active_streams(self) -> list[dict]:
        streams = []
        page = None
        try:
            page = await self._context.new_page()
            await page.goto(
                f"{EXPLORE_URL}?category=trading-cards",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(3000)

            stream_links = await page.evaluate("""
                () => {
                    const results = [];
                    document.querySelectorAll('a[href*="/live/"]').forEach(a => {
                        const href = a.href;
                        const match = href.match(/\\/live\\/([a-f0-9-]{36})/);
                        if (!match) return;
                        const stream_id = match[1];
                        const title = (a.innerText || a.textContent || '').toLowerCase().trim();
                        const seller = a.closest('[data-testid]')?.querySelector('img')?.alt || '';
                        results.push({ stream_id, title, seller, url: href });
                    });
                    return results;
                }
            """)

            seen = set()
            for s in stream_links:
                sid = s.get("stream_id", "")
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                title = s.get("title", "").lower()
                if any(kw in title for kw in POKEMON_KEYWORDS):
                    streams.append({
                        "stream_id": sid,
                        "seller": s.get("seller") or "unknown",
                        "url": s.get("url"),
                        "title": s.get("title"),
                    })

            logger.info(f"StreamFinder: found {len(streams)} Pokemon streams")

        except Exception as e:
            logger.error(f"StreamFinder error: {e}")
        finally:
            if page and not page.is_closed():
                await page.close()

        return streams

    async def poll(self, on_new_stream, on_ended_stream=None):
        logger.info("StreamFinder polling started")
        while True:
            try:
                streams = await self.get_active_streams()
                current_ids = {s["stream_id"] for s in streams}

                for s in streams:
                    if s["stream_id"] not in self._known_ids:
                        self._known_ids.add(s["stream_id"])
                        await on_new_stream(s)

                if on_ended_stream:
                    ended = self._known_ids - current_ids
                    for stream_id in ended:
                        self._known_ids.discard(stream_id)
                        await on_ended_stream(stream_id)

            except Exception as e:
                logger.error(f"StreamFinder poll error: {e}")

            await asyncio.sleep(POLL_INTERVAL)
