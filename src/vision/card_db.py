"""
Pokemon card database builder and perceptual hash index.

Sources:
  1. PokemonTCG.io API  — card metadata + image URLs
  2. Whatnot listing image — from media[0].key on whatnot-images bucket

Flow:
  - Download card images from PokemonTCG.io
  - Compute perceptual hash (pHash) for each
  - Store in SQLite: card_id, name, set, number, image_url, phash
  - At query time: compute pHash of captured frame, find nearest match
"""

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import imagehash
import requests
from PIL import Image

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "cards.db"
IMAGES_DIR = Path(__file__).parent.parent.parent / "data" / "card_images"
POKEMONTCG_API = "https://api.pokemontcg.io/v2"
HASH_DISTANCE_THRESHOLD = 15


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            card_id     TEXT PRIMARY KEY,
            name        TEXT,
            set_name    TEXT,
            set_id      TEXT,
            number      TEXT,
            image_url   TEXT,
            phash       TEXT,
            created_at  INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auction_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_id       TEXT,
            listing_id      TEXT,
            card_id         TEXT,
            card_name       TEXT,
            sold_price_cents INTEGER,
            buyer_username  TEXT,
            bid_count       INTEGER,
            seller_user_id  TEXT,
            image_key       TEXT,
            confidence      REAL,
            frame_path      TEXT,
            ended_at        INTEGER,
            created_at      INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_auction_results_ended_at ON auction_results(ended_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_auction_results_stream_id ON auction_results(stream_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_auction_results_card_name ON auction_results(card_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_phash ON cards(phash) WHERE phash IS NOT NULL")
    conn.commit()
    conn.close()
    logger.info("DB initialized")


def download_card_images(api_key: str = None, max_pages: int = None):
    """Download all Pokemon cards from PokemonTCG.io and build hash index.
    Resumes automatically from where it left off (skips already-downloaded cards).
    """
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"X-Api-Key": api_key} if api_key else {}
    conn = get_db()
    page = 1
    page_size = 250
    max_retries = 5

    while True:
        logger.info(f"Fetching page {page}...")

        resp = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(
                    f"{POKEMONTCG_API}/cards",
                    params={"page": page, "pageSize": page_size, "select": "id,name,set,number,images"},
                    headers=headers,
                    timeout=60,
                )
                resp.raise_for_status()
                break
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    logger.info(f"Page {page} returned 404 — end of database reached")
                    conn.close()
                    logger.info("Card database built")
                    return
                logger.warning(f"Page {page} attempt {attempt}/{max_retries} failed: {e}")
                if attempt == max_retries:
                    logger.error(f"Giving up on page {page} after {max_retries} attempts")
                    conn.close()
                    return
                time.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"Page {page} attempt {attempt}/{max_retries} failed: {e}")
                if attempt == max_retries:
                    logger.error(f"Giving up on page {page} after {max_retries} attempts")
                    conn.close()
                    return
                time.sleep(2 ** attempt)

        data = resp.json()
        cards = data.get("data", [])

        if not cards:
            break

        for card in cards:
            card_id = card["id"]
            existing = conn.execute("SELECT card_id FROM cards WHERE card_id=?", (card_id,)).fetchone()
            if existing and existing["card_id"]:
                continue

            image_url = card.get("images", {}).get("large") or card.get("images", {}).get("small")
            if not image_url:
                continue

            phash = _download_and_hash(card_id, image_url)

            conn.execute("""
                INSERT OR REPLACE INTO cards (card_id, name, set_name, set_id, number, image_url, phash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                card_id,
                card.get("name"),
                card.get("set", {}).get("name"),
                card.get("set", {}).get("id"),
                card.get("number"),
                image_url,
                phash,
            ))

        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        logger.info(f"Page {page} done — {len(cards)} cards | total in DB: {total}")

        if max_pages and page >= max_pages:
            break
        if len(cards) < page_size:
            break

        page += 1
        time.sleep(0.1)

    conn.close()
    logger.info("Card database built")


def _download_and_hash(card_id: str, image_url: str) -> Optional[str]:
    img_path = IMAGES_DIR / f"{card_id.replace('/', '_')}.jpg"

    if not img_path.exists():
        try:
            r = requests.get(image_url, timeout=15)
            r.raise_for_status()
            with open(img_path, "wb") as f:
                f.write(r.content)
        except Exception as e:
            logger.warning(f"Failed to download {image_url}: {e}")
            return None

    try:
        img = Image.open(img_path)
        return str(imagehash.phash(img))
    except Exception as e:
        logger.warning(f"Failed to hash {img_path}: {e}")
        return None


def save_auction_result(
    stream_id: str,
    listing_id: str,
    card_id: Optional[str],
    card_name: str,
    sold_price_cents: int,
    buyer_username: str,
    bid_count: int,
    seller_user_id: str,
    image_key: Optional[str],
    confidence: float,
    frame_path: Optional[str],
    ended_at: int,
):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO auction_results
            (stream_id, listing_id, card_id, card_name, sold_price_cents, buyer_username,
             bid_count, seller_user_id, image_key, confidence, frame_path, ended_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            stream_id, listing_id, card_id, card_name, sold_price_cents,
            buyer_username, bid_count, seller_user_id, image_key,
            confidence, frame_path, ended_at,
        ))
        conn.commit()
    finally:
        conn.close()
