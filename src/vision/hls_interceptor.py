"""
Intercepts the IVS HLS .m3u8 URL from the Whatnot stream page.
Run alongside the existing Playwright session.
"""

import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

IVS_PATTERN = re.compile(r"https://[^\"'\s]+\.m3u8[^\"'\s]*")


class HLSInterceptor:
    def __init__(self):
        self._hls_url: Optional[str] = None
        self._found = asyncio.Event()

    def attach(self, page):
        page.on("request", self._on_request)
        page.on("response", self._on_response)

    def _on_request(self, request):
        url = request.url
        if ".m3u8" in url and "ivs" in url.lower():
            logger.info(f"[HLS] Found IVS URL via request: {url}")
            self._hls_url = url
            self._found.set()

    def _on_response(self, response):
        url = response.url
        if ".m3u8" in url and "ivs" in url.lower():
            logger.info(f"[HLS] Found IVS URL via response: {url}")
            self._hls_url = url
            self._found.set()

    async def wait_for_url(self, timeout: float = 30.0) -> Optional[str]:
        try:
            await asyncio.wait_for(self._found.wait(), timeout=timeout)
            return self._hls_url
        except asyncio.TimeoutError:
            logger.warning("HLS URL not found within timeout — stream may be Agora WebRTC")
            return None

    @property
    def url(self) -> Optional[str]:
        return self._hls_url
