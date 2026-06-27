"""
Shared perceptual hash index — loaded once at startup, queried by all StreamWorkers.

Instead of hitting SQLite on every auction_ended event, we load all 14k hashes
into memory once and do in-process nearest-neighbor search.
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

import imagehash
import requests
from PIL import Image

logger = logging.getLogger(__name__)

HASH_DISTANCE_THRESHOLD = 10
IMAGES_DIR = Path(__file__).parent.parent.parent / "data" / "card_images"


class HashIndex:
    def __init__(self):
        self._hashes: list[tuple] = []
        self._loaded = False

    def load(self, db_path: str):
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT card_id, name, set_name, set_id, number, image_url, phash FROM cards WHERE phash IS NOT NULL"
        ).fetchall()
        conn.close()

        self._hashes = []
        for row in rows:
            try:
                h = imagehash.hex_to_hash(row["phash"])
                self._hashes.append((h, dict(row)))
            except Exception:
                continue

        self._loaded = True
        logger.info(f"HashIndex loaded {len(self._hashes)} cards into memory")

    def find(self, img_path: str) -> Optional[dict]:
        if not self._loaded or not self._hashes:
            logger.warning("HashIndex not loaded")
            return None

        try:
            query_hash = imagehash.phash(Image.open(img_path))
        except Exception as e:
            logger.error(f"Failed to hash image {img_path}: {e}")
            return None

        best_match = None
        best_distance = float("inf")

        for db_hash, card in self._hashes:
            distance = query_hash - db_hash
            if distance < best_distance:
                best_distance = distance
                best_match = card

        if best_match and best_distance <= HASH_DISTANCE_THRESHOLD:
            result = dict(best_match)
            result["confidence"] = max(0.0, 1.0 - (best_distance / HASH_DISTANCE_THRESHOLD))
            logger.info(f"Hash match: {result['name']} distance={best_distance} confidence={result['confidence']:.2f}")
            return result

        logger.info(f"No hash match (best distance={best_distance})")
        return None

    def find_from_whatnot_image(self, image_key: str) -> Optional[dict]:
        url = f"https://images.whatnot.com/{image_key}"
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            tmp.write(r.content)
            tmp.flush()
            tmp.close()
            return self.find(tmp.name)
        except Exception as e:
            logger.error(f"Failed to fetch Whatnot image {image_key}: {e}")
            return None
        finally:
            Path(tmp.name).unlink(missing_ok=True)


_shared_index = HashIndex()


def get_index() -> HashIndex:
    return _shared_index
