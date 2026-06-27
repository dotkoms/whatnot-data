"""
Detects and crops the Pokemon card region from a stream frame.

Strategy:
1. Look for a rectangle with ~63:88 aspect ratio (standard Pokemon card)
2. Use edge detection + contour finding via OpenCV
3. Return cropped card image for identification
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

CARD_ASPECT = 63 / 88
ASPECT_TOLERANCE = 0.15
MIN_CARD_AREA_RATIO = 0.05


def detect_card(frame_path: str) -> Optional[np.ndarray]:
    """
    Detect and return a cropped card image from the frame.
    Returns None if no card detected.
    """
    img = cv2.imread(frame_path)
    if img is None:
        logger.error(f"Could not read frame: {frame_path}")
        return None

    h, w = img.shape[:2]
    frame_area = h * w

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for contour in contours[:10]:
        area = cv2.contourArea(contour)
        if area < frame_area * MIN_CARD_AREA_RATIO:
            break

        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

        if len(approx) == 4:
            x, y, cw, ch = cv2.boundingRect(approx)
            aspect = cw / ch if ch > 0 else 0

            if abs(aspect - CARD_ASPECT) < ASPECT_TOLERANCE:
                cropped = img[y:y+ch, x:x+cw]
                logger.info(f"Card detected at ({x},{y}) size {cw}x{ch} aspect={aspect:.3f}")
                return cropped

    logger.debug("No card contour found — using center crop fallback")
    return _center_crop(img)


def _center_crop(img: np.ndarray) -> np.ndarray:
    """Crop the center 60% of the frame as a fallback."""
    h, w = img.shape[:2]
    x1 = int(w * 0.2)
    x2 = int(w * 0.8)
    y1 = int(h * 0.1)
    y2 = int(h * 0.9)
    return img[y1:y2, x1:x2]


def save_crop(crop: np.ndarray, frame_path: str) -> str:
    """Save cropped card image next to the original frame."""
    p = Path(frame_path)
    crop_path = str(p.parent / f"{p.stem}_card.jpg")
    cv2.imwrite(crop_path, crop)
    return crop_path
