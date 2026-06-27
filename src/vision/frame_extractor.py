"""
Extracts frames from an HLS stream every N seconds using ffmpeg.
Falls back to Playwright screenshots for Agora WebRTC streams.
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FRAMES_DIR = Path(__file__).parent.parent.parent / "data" / "frames"


class FrameExtractor:
    def __init__(self, stream_id: str, interval: int = 30):
        self.stream_id = stream_id
        self.interval = interval
        self.output_dir = FRAMES_DIR / stream_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._running = False

    async def start_hls(self, hls_url: str, on_frame=None):
        """Extract frames from IVS HLS stream via ffmpeg."""
        self._running = True
        logger.info(f"Starting HLS frame extraction from {hls_url}")

        while self._running:
            ts = int(time.time())
            frame_path = self.output_dir / f"frame_{ts}.jpg"

            cmd = [
                "ffmpeg",
                "-y",
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
            await proc.wait()

            if frame_path.exists():
                logger.info(f"Frame captured: {frame_path}")
                if on_frame:
                    await on_frame(str(frame_path), ts)
            else:
                logger.warning(f"ffmpeg failed to capture frame at {ts}")

            await asyncio.sleep(self.interval)

    async def start_screenshot(self, page, on_frame=None):
        """Fallback: take browser screenshots for Agora WebRTC streams."""
        self._running = True
        logger.info("Starting Agora screenshot frame extraction")

        while self._running:
            ts = int(time.time())
            frame_path = self.output_dir / f"frame_{ts}.jpg"

            await page.screenshot(path=str(frame_path), type="jpeg", quality=85)
            logger.info(f"Screenshot captured: {frame_path}")

            if on_frame:
                await on_frame(str(frame_path), ts)

            await asyncio.sleep(self.interval)

    def stop(self):
        self._running = False
