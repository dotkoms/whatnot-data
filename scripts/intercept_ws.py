"""
Run this script pointed at a live Whatnot stream URL.
Logs in with credentials from .env, then prints all auction/live
Phoenix WebSocket frames (filters out Agora video and chat).

Usage:
    python scripts/intercept_ws.py
"""

import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

STREAM_URL = "https://www.whatnot.com/live/0f68dac0-ced4-4c21-bf0a-f9b0b79b03d0"
LOGIN_URL = "https://www.whatnot.com/login"


IGNORE_HOSTS = ("sd-rtn.com", "agora.io")
IGNORE_TOPICS = ("chat:", "phoenix")
IGNORE_EVENTS = ("giveaway_entry_count_updated", "livestream_view_count_updated", "reactions")


def should_ignore(url, topic, event=""):
    if any(h in url for h in IGNORE_HOSTS):
        return True
    if any(str(topic).startswith(t) for t in IGNORE_TOPICS):
        return True
    if event in IGNORE_EVENTS:
        return True
    return False


SESSION_DIR = os.path.join(os.path.dirname(__file__), "../data/session")

async def intercept(stream_url: str):
    async with async_playwright() as p:
        os.makedirs(SESSION_DIR, exist_ok=True)
        context = await p.firefox.launch_persistent_context(
            SESSION_DIR,
            headless=False,
        )
        page = context.pages[0] if context.pages else await context.new_page()

        def _save_token(token: str):
            env_path = os.path.join(os.path.dirname(__file__), "../.env")
            with open(env_path, "r") as f:
                lines = f.readlines()
            with open(env_path, "w") as f:
                for line in lines:
                    if line.startswith("WHATNOT_AUTH_TOKEN="):
                        f.write(f"WHATNOT_AUTH_TOKEN={token}\n")
                        print(f"\n✅ Auth token saved to .env\n")
                    else:
                        f.write(line)

        def on_websocket(ws):
            if any(h in ws.url for h in IGNORE_HOSTS):
                return
            if "token=" in ws.url:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(ws.url).query)
                token = (qs.get("token") or qs.get("vsn") or [None])[0]
                if token and token != "2.0.0":
                    _save_token(token)
            print(f"\n[WS OPENED] {ws.url}\n")

            def on_frame_sent(payload):
                try:
                    data = json.loads(payload)
                    topic = data[2] if isinstance(data, list) and len(data) > 2 else "?"
                    event = data[3] if isinstance(data, list) and len(data) > 3 else "?"
                    if should_ignore(ws.url, topic, event):
                        return
                    print(f"[SENT] topic={topic} event={event}")
                    print(json.dumps(data, indent=2))
                except Exception:
                    print(f"[SENT RAW] {payload}")

            def on_frame_received(payload):
                try:
                    data = json.loads(payload)
                    topic = data[2] if isinstance(data, list) and len(data) > 2 else "?"
                    event = data[3] if isinstance(data, list) and len(data) > 3 else "?"
                    if should_ignore(ws.url, topic, event):
                        return
                    print(f"[RECV] topic={topic} event={event}")
                    print(json.dumps(data, indent=2))
                except Exception:
                    print(f"[RECV RAW] {payload}")

            ws.on("framesent", lambda frame: on_frame_sent(frame))
            ws.on("framereceived", lambda frame: on_frame_received(frame))
            ws.on("close", lambda: print(f"[WS CLOSED] {ws.url}"))

        page.on("websocket", on_websocket)

        already_logged_in = "whatnot.com" in page.url and "login" not in page.url
        if not already_logged_in:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            current = page.url
            print("\n⚠️  Not logged in. Please log in manually in the browser window (including SMS code).")
            print("Waiting until you are redirected away from the login page...\n")
            while "login" in page.url or "verify" in page.url or "confirm" in page.url:
                await asyncio.sleep(1)
            print(f"✅ Logged in. Current URL: {page.url}\n")

        print(f"Navigating to {stream_url} ...")
        await page.goto(stream_url, wait_until="domcontentloaded", timeout=60000)

        print("Listening for WebSocket frames. Press Ctrl+C to stop.\n")
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

        await context.close()


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) >= 2 else STREAM_URL
    asyncio.run(intercept(url))
