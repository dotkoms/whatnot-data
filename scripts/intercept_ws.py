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

STREAM_URL = "https://www.whatnot.com/live/822a77d5-5fad-4de7-9036-e04229fc213e"
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


async def login(page, email: str, password: str):
    print(f"Logging in as {email} ...")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    inputs = await page.locator('input').all()
    print(f"Found {len(inputs)} inputs on login page:")
    for i, inp in enumerate(inputs):
        t = await inp.get_attribute("type")
        n = await inp.get_attribute("name")
        p = await inp.get_attribute("placeholder")
        print(f"  [{i}] type={t} name={n} placeholder={p}")

    all_inputs = page.locator('input')
    count = await all_inputs.count()
    for i in range(count):
        inp = all_inputs.nth(i)
        t = await inp.get_attribute("type")
        if t in ("email", "text", None):
            await inp.fill(email)
            print(f"Filled email into input[{i}]")
            break

    for i in range(count):
        inp = all_inputs.nth(i)
        t = await inp.get_attribute("type")
        if t == "password":
            await inp.fill(password)
            print(f"Filled password into input[{i}]")
            break

    await page.wait_for_timeout(500)

    submitted = False
    for selector in ['button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Log in")', 'button:has-text("Continue")']:
        btn = page.locator(selector)
        if await btn.count() > 0:
            await btn.first.click()
            print(f"Clicked: {selector}")
            submitted = True
            break

    if not submitted:
        await page.keyboard.press("Enter")
        print("Pressed Enter to submit")

    await page.wait_for_timeout(6000)
    print(f"Login attempted, current URL: {page.url}\n")


SESSION_DIR = os.path.join(os.path.dirname(__file__), "../data/session")

async def intercept(stream_url: str, email: str = None, password: str = None):
    async with async_playwright() as p:
        os.makedirs(SESSION_DIR, exist_ok=True)
        context = await p.firefox.launch_persistent_context(
            SESSION_DIR,
            headless=False,
        )
        page = context.pages[0] if context.pages else await context.new_page()

        def on_websocket(ws):
            if any(h in ws.url for h in IGNORE_HOSTS):
                return
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
    email = os.environ.get("WHATNOT_EMAIL")
    password = os.environ.get("WHATNOT_PASSWORD")
    url = sys.argv[1] if len(sys.argv) >= 2 else STREAM_URL
    asyncio.run(intercept(url, email=email, password=password))
