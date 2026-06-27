"""
Multi-stream orchestrator entry point.

Automatically discovers all live Pokemon card streams on Whatnot
and monitors them simultaneously (up to 20 concurrent).

Usage:
    python3 orchestrate.py

Or to monitor a specific stream directly:
    python3 orchestrate.py https://www.whatnot.com/live/<stream_id>

Requires:
    - data/session/ Firefox session (run scripts/intercept_ws.py once to log in)
    - data/cards.db  (run scripts/build_card_db.py first)
    - WHATNOT_AUTH_TOKEN in .env (run scripts/intercept_ws.py to capture it)
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from src.discovery.orchestrator import Orchestrator
from src.vision.card_db import init_db, DB_PATH
from src.vision.hash_index import get_index

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SESSION_DIR = str(Path(__file__).parent / "data" / "session")
LOGIN_URL = "https://www.whatnot.com/login"


async def _ensure_logged_in(page):
    if "login" in page.url or "verify" in page.url or page.url == "about:blank":
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    if "login" in page.url or "verify" in page.url:
        logger.warning("Not logged in — log in manually in the browser window.")
        while "login" in page.url or "verify" in page.url or "confirm" in page.url:
            await asyncio.sleep(1)
        logger.info(f"Logged in. URL: {page.url}")


async def run(specific_stream_id: str = None):
    auth_token = os.environ.get("WHATNOT_AUTH_TOKEN")
    if not auth_token:
        logger.warning("No WHATNOT_AUTH_TOKEN set — auction events may not be received. Run scripts/intercept_ws.py first.")

    init_db()
    index = get_index()
    index.load(str(DB_PATH))
    logger.info(f"Hash index loaded")

    async with async_playwright() as p:
        os.makedirs(SESSION_DIR, exist_ok=True)
        context = await p.firefox.launch_persistent_context(
            SESSION_DIR,
            headless=False,
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await _ensure_logged_in(page)
        await page.close()

        orchestrator = Orchestrator(
            browser_context=context,
            auth_token=auth_token,
        )

        if specific_stream_id:
            logger.info(f"Monitoring specific stream: {specific_stream_id}")
            await orchestrator.add_stream(specific_stream_id)
            await orchestrator._monitor_workers()
        else:
            logger.info("Auto-discovering Pokemon card streams...")
            await orchestrator.start()

        await context.close()


if __name__ == "__main__":
    specific = None
    if len(sys.argv) >= 2:
        url = sys.argv[1]
        specific = url.rstrip("/").split("/")[-1]

    asyncio.run(run(specific))
