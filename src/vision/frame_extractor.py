"""
Extracts frames from an HLS stream every N seconds using ffmpeg.
Falls back to Playwright screenshots for Agora WebRTC streams.

For Agora streams, crops to the video player region (left ~65% of page)
to exclude chat sidebar and UI chrome before card detection.
"""

import asyncio
import logging
import time
from pathlib import Path

import cv2

logger = logging.getLogger(__name__)

FRAMES_DIR = Path(__file__).parent.parent.parent / "data" / "frames"
FFMPEG_TIMEOUT = 30
MAX_FRAMES_PER_STREAM = 120

VIDEO_REGION_X = 0.0
VIDEO_REGION_Y = 0.0
VIDEO_REGION_W = 0.65
VIDEO_REGION_H = 1.0


class FrameExtractor:
    def __init__(self, stream_id: str, interval: int = 30):
        self.stream_id = stream_id
        self.interval = interval
        self.output_dir = FRAMES_DIR / stream_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._running = False

    async def start_hls(self, hls_url: str, on_frame=None):
        self._running = True
        logger.info(f"Starting HLS frame extraction from {hls_url}")

        while self._running:
            ts = int(time.time())
            frame_path = self.output_dir / f"frame_{ts}.jpg"

            cmd = [
                "ffmpeg", "-y",
                "-i", hls_url,
                "-vframes", "1",
                "-q:v", "2",
                str(frame_path),
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=FFMPEG_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning(f"[{self.stream_id}] ffmpeg timed out after {FFMPEG_TIMEOUT}s — killed")
                await asyncio.sleep(self.interval)
                continue

            if frame_path.exists():
                logger.info(f"Frame captured: {frame_path}")
                self._rotate_frames()
                if on_frame:
                    await on_frame(str(frame_path), ts)
            else:
                logger.warning(f"ffmpeg failed to capture frame at {ts}")

            await asyncio.sleep(self.interval)

    async def start_screenshot(self, page, on_frame=None):
        self._running = True
        logger.info("Starting Agora screenshot frame extraction")

        while self._running:
            ts = int(time.time())
            raw_path = self.output_dir / f"frame_{ts}_raw.jpg"
            frame_path = self.output_dir / f"frame_{ts}.jpg"

            try:
                await page.screenshot(path=str(raw_path), type="jpeg", quality=85)

                img = cv2.imread(str(raw_path))
                if img is not None:
                    h, w = img.shape[:2]
                    x1 = int(w * VIDEO_REGION_X)
                    x2 = int(w * (VIDEO_REGION_X + VIDEO_REGION_W))
                    y1 = int(h * VIDEO_REGION_Y)
                    y2 = int(h * (VIDEO_REGION_Y + VIDEO_REGION_H))
                    cropped = img[y1:y2, x1:x2]
                    cv2.imwrite(str(frame_path), cropped)
                    raw_path.unlink(missing_ok=True)
                    logger.info(f"Screenshot captured (cropped to video region): {frame_path}")
                else:
                    raw_path.rename(frame_path)
                    logger.info(f"Screenshot captured: {frame_path}")

                self._rotate_frames()
                if on_frame:
                    await on_frame(str(frame_path), ts)

            except Exception as e:
                logger.error(f"Screenshot failed: {e}")
                raw_path.unlink(missing_ok=True)

            await asyncio.sleep(self.interval)

    def _rotate_frames(self):
        frames = sorted(self.output_dir.glob("frame_*.jpg"))
        if len(frames) > MAX_FRAMES_PER_STREAM:
            for old in frames[:len(frames) - MAX_FRAMES_PER_STREAM]:
                old.unlink(missing_ok=True)

    def stop(self):
        self._running = False
