"""
Card identification pipeline.

Priority order:
  1. Whatnot listing image (from auction_ended media[0].key) — most accurate
  2. Perceptual hash match on captured frame crop
  3. OCR fallback — read card name/number text from frame
"""

import logging
import re
from typing import Optional

import cv2
import pytesseract

from .card_db import find_card_by_hash, find_card_by_whatnot_image
from .card_detector import detect_card, save_crop

logger = logging.getLogger(__name__)


class CardIdentifier:
    async def identify(
        self,
        frame_path: Optional[str] = None,
        whatnot_image_key: Optional[str] = None,
    ) -> Optional[dict]:

        if whatnot_image_key:
            result = find_card_by_whatnot_image(whatnot_image_key)
            if result:
                result["method"] = "whatnot_image"
                return result

        if frame_path:
            crop = detect_card(frame_path)
            if crop is not None:
                crop_path = save_crop(crop, frame_path)

                result = find_card_by_hash(crop_path)
                if result:
                    result["method"] = "phash"
                    result["crop_path"] = crop_path
                    return result

                result = self._ocr_identify(crop_path)
                if result:
                    result["method"] = "ocr"
                    result["crop_path"] = crop_path
                    return result

        return None

    def _ocr_identify(self, crop_path: str) -> Optional[dict]:
        """Use Tesseract OCR to read card name and number from the card image."""
        try:
            import cv2
            img = cv2.imread(crop_path)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
            text = pytesseract.image_to_string(thresh, config="--psm 6")
            logger.debug(f"OCR text: {text[:200]}")

            number_match = re.search(r"\b(\d{1,3})/(\d{1,3})\b", text)
            card_number = number_match.group(0) if number_match else None

            lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 2]
            card_name = lines[0] if lines else None

            if card_name or card_number:
                return {
                    "card_id": None,
                    "name": card_name,
                    "number": card_number,
                    "ocr_text": text,
                    "confidence": 0.4,
                }
        except Exception as e:
            logger.warning(f"OCR failed: {e}")

        return None
