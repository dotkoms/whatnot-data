"""
StreamFinder — scrapes active Pokemon card streams from Whatnot.

Polls whatnot.com/explore every 60 seconds.
Filters for Pokemon card streams by category + title keywords.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

TAG_URLS = [
    "https://www.whatnot.com/tag/pokemon",
]
POKEMON_KEYWORDS = [
    "pokemon", "poke", "tcg", "cards", "charizard", "pikachu", "pack",
    "booster", "vintage", "break", "pull", "ex", "gx", "vmax", "vstar",
    "holo", "psa", "bgs", "graded", "sealed", "evolving", "obsidian",
    "scarlet", "violet", "151", "jungle", "fossil", "base set",
]
NON_POKEMON_KEYWORDS = ["yugioh", "yu-gi-oh", "magic", "mtg", "sports", "baseball", "basketball", "football", "soccer", "nfl", "nba", "mlb"]
POLL_INTERVAL = 60


class StreamFinder:
    def __init__(self, browser_context):
        self._context = browser_context
        self._known_ids: set[str] = set()

    async def _scrape_tag_page(self, page, url: str) -> list[dict]:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        return await page.evaluate("""
            () => {
                const results = [];
                const seen = new Set();
                document.querySelectorAll('a[href*="/live/"]').forEach(a => {
                    const href = a.href;
                    const m = href.match(/\\/live\\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
                    if (!m || seen.has(m[1])) return;
                    seen.add(m[1]);
                    const card = a.closest('[data-testid="livestream-card"]') || a.closest('[data-type="LivestreamCard"]') || a;
                    const title = (card.innerText || card.textContent || '').toLowerCase().trim().split('\\n')[0];
                    const img = card.querySelector('img');
                    const seller = img ? (img.alt || '') : '';
                    results.push({ stream_id: m[1], title, seller, url: href });
                });
                return results;
            }
        """)

    async def get_active_streams(self) -> list[dict]:
        streams = []
        page = None
        try:
            page = await self._context.new_page()
            all_links = []
            for tag_url in TAG_URLS:
                try:
                    links = await self._scrape_tag_page(page, tag_url)
                    all_links.extend(links)
                except Exception as e:
                    logger.warning(f"StreamFinder: error scraping {tag_url}: {e}")
            stream_links = all_links

            seen = set()
            for s in stream_links:
                sid = s.get("stream_id", "")
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                title = s.get("title", "").lower()
                if any(kw in title for kw in NON_POKEMON_KEYWORDS):
                    continue
                is_pokemon = any(kw in title for kw in POKEMON_KEYWORDS)
                streams.append({
                    "stream_id": sid,
                    "seller": s.get("seller") or "unknown",
                    "url": s.get("url"),
                    "title": s.get("title"),
                    "priority": 1 if is_pokemon else 0,
                })

            streams.sort(key=lambda x: x["priority"], reverse=True)

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
