"""
One-time script to build the Pokemon card hash database.

Downloads all cards from PokemonTCG.io, saves images, computes pHash.
Stores everything in data/cards.db.

Usage:
    python scripts/build_card_db.py

Optional: set POKEMONTCG_API_KEY in .env for higher rate limits (free at pokemontcg.io).
Estimated time: ~30-60 min for full database (~20k cards).
Run with --pages 5 to test with just the first 5 pages (~1250 cards).
"""

import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.vision.card_db import init_db, download_card_images

if __name__ == "__main__":
    max_pages = None
    if "--pages" in sys.argv:
        idx = sys.argv.index("--pages")
        max_pages = int(sys.argv[idx + 1])

    api_key = os.environ.get("POKEMONTCG_API_KEY")
    print(f"Building card database (api_key={'set' if api_key else 'not set'}, max_pages={max_pages or 'all'})")

    init_db()
    download_card_images(api_key=api_key, max_pages=max_pages)
    print("Done.")
