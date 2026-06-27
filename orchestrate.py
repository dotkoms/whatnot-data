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
    - HEADLESS=true in .env for server deployments
"""

import asyncio
import logging
import os
import signal
import sqlite3
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


def _validate_startup():
    auth_token = os.environ.get("WHATNOT_AUTH_TOKEN")
    if not auth_token:
        logger.error(
            "\n\n❌ WHATNOT_AUTH_TOKEN is not set.\n"
            "   Run:  python scripts/intercept_ws.py\n"
            "   Then copy the token into your .env file and restart.\n"
        )
        sys.exit(1)

    if not DB_PATH.exists():
        logger.error(
            f"\n\n❌ Card database not found at {DB_PATH}\n"
            "   Run:  python scripts/build_card_db.py\n"
            "   Then copy data/cards.db to the server and restart.\n"
        )
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    count = conn.execute("SELECT COUNT(*) FROM cards WHERE phash IS NOT NULL").fetchone()[0]
    conn.close()
    if count == 0:
        logger.error(
            f"\n\n❌ Card database exists but has no hashed cards.\n"
            "   Run:  python scripts/build_card_db.py\n"
        )
        sys.exit(1)

    logger.info(f"Startup validation passed — {count} cards in DB, auth token present")
    return auth_token


async def _ensure_logged_in(page, headless: bool):
    if "login" in page.url or "verify" in page.url or page.url == "about:blank":
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    if "login" in page.url or "verify" in page.url:
        if headless:
            logger.error(
                "\n\n❌ Browser session expired or not found.\n"
                "   Run locally first:  python scripts/intercept_ws.py\n"
                "   Then copy data/session/ to the server and restart.\n"
            )
            sys.exit(1)
        logger.warning("Not logged in — log in manually in the browser window.")
        while "login" in page.url or "verify" in page.url or "confirm" in page.url:
            await asyncio.sleep(1)
        logger.info(f"Logged in. URL: {page.url}")


async def run(specific_stream_id: str = None):
    auth_token = _validate_startup()
    headless = os.environ.get("HEADLESS", "true").lower() == "true"

    init_db()
    index = get_index()
    index.load(str(DB_PATH))
    logger.info("Hash index loaded")

    loop = asyncio.get_running_loop()

    async with async_playwright() as p:
        os.makedirs(SESSION_DIR, exist_ok=True)
        context = await p.firefox.launch_persistent_context(
            SESSION_DIR,
            headless=headless,
        )

        stop_event = asyncio.Event()

        def _handle_signal():
            logger.info("Shutdown signal received — stopping gracefully")
            stop_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _handle_signal)

        page = context.pages[0] if context.pages else await context.new_page()
        await _ensure_logged_in(page, headless)
        await page.close()

        orchestrator = Orchestrator(
            browser_context=context,
            auth_token=auth_token,
        )

        async def _main():
            if specific_stream_id:
                logger.info(f"Monitoring specific stream: {specific_stream_id}")
                await orchestrator.add_stream(specific_stream_id)
                await orchestrator._monitor_workers()
            else:
                logger.info("Auto-discovering Pokemon card streams...")
                await orchestrator.start()

        main_task = asyncio.create_task(_main())
        await asyncio.wait(
            [main_task, asyncio.create_task(stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )

        main_task.cancel()
        try:
            await main_task
        except asyncio.CancelledError:
            pass

        await context.close()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    specific = None
    if len(sys.argv) >= 2:
        url = sys.argv[1]
        specific = url.rstrip("/").split("/")[-1]

    asyncio.run(run(specific))
