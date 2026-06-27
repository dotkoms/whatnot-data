# Whatnot Pokemon Card Auction Tracker — Master Plan

## Current State Audit

### What exists and works
| Component | File | Status |
|---|---|---|
| Phoenix WS client | `src/ws/phoenix_client.py` | ✅ Working — joins `auction:` + `commerce:` topics |
| Event handler | `src/ws/event_handler.py` | ✅ Working — handles `auction_ended`, `bid_placed`, `payment_succeeded` |
| Discord bot | `src/discord/bot.py` | ✅ Built — needs `DISCORD_BOT_TOKEN` + `DISCORD_CHANNEL_ID` in `.env` |
| HLS interceptor | `src/vision/hls_interceptor.py` | ⚠️ Built but never attached to a browser page |
| Frame extractor | `src/vision/frame_extractor.py` | ⚠️ Built — ffmpeg + screenshot fallback, but never called in main |
| Card detector | `src/vision/card_detector.py` | ⚠️ Built — OpenCV 63:88 aspect ratio crop, untested on real frames |
| Card identifier | `src/vision/card_identifier.py` | ⚠️ Built — 3-tier pipeline, but DB is empty |
| Card DB | `src/vision/card_db.py` | ❌ DB not built — `data/cards.db` does not exist |
| DB builder script | `scripts/build_card_db.py` | ❌ Never run — no card images, no hashes |
| Main entry point | `main.py` | ❌ Broken — HLSInterceptor never gets a browser page attached |
| Playwright session | `scripts/intercept_ws.py` | ✅ Works for debugging only — not integrated into main |

### What is missing
1. **No Pokemon card database** — `data/cards.db` does not exist. Zero cards. Identification cannot work.
2. **Browser not connected to main pipeline** — `main.py` starts `HLSInterceptor` but never opens a browser page.
3. **No stream discovery** — only handles one hardcoded stream URL; cannot auto-discover active Pokemon streams.
4. **No multi-stream support** — one `PhoenixClient` per stream; no orchestrator.
5. **Discord bot not configured** — tokens not set in `.env`.

---

## Architecture (Target)

```
┌─────────────────────────────────────────────────────────────┐
│                        Orchestrator                         │
│  Polls Whatnot /explore for live Pokemon card streams       │
│  Spawns StreamWorker per stream (up to N concurrent)        │
└──────────────────────┬──────────────────────────────────────┘
                       │ one per stream
         ┌─────────────▼──────────────┐
         │       StreamWorker         │
         │                            │
         │  ┌──────────────────────┐  │
         │  │  Playwright Browser  │  │
         │  │  Firefox persistent  │  │
         │  │  - navigates stream  │  │
         │  │  - intercepts HLS    │  │
         │  │  - screenshots if    │  │
         │  │    Agora (no HLS)    │  │
         │  └──────────┬───────────┘  │
         │             │              │
         │  ┌──────────▼───────────┐  │
         │  │   FrameExtractor     │  │
         │  │  ffmpeg every 30s    │  │
         │  │  → frame_path        │  │
         │  └──────────┬───────────┘  │
         │             │              │
         │  ┌──────────▼───────────┐  │
         │  │  AuctionEventHandler │  │
         │  │  Phoenix WS client   │  │
         │  │  On auction_ended:   │  │
         │  │  1. check listing img│  │
         │  │  2. or last frame    │  │
         │  │  3. CardIdentifier   │  │
         │  │  4. save to SQLite   │  │
         │  │  5. post Discord     │  │
         │  └──────────────────────┘  │
         └────────────────────────────┘
                       │
         ┌─────────────▼──────────────┐
         │        SQLite DB           │
         │  cards (~20k pHash index)  │
         │  auction_results           │
         └────────────────────────────┘
                       │
         ┌─────────────▼──────────────┐
         │      Discord Bot           │
         │  bid / sold / start events │
         └────────────────────────────┘
```

---

## Phase 1 — Fix Core Pipeline (DO FIRST)

**Goal:** One stream, end-to-end — WS events → card identified → Discord post → DB saved.

### Step 1.1 — Build Pokemon Card Database ❌ BLOCKER

Without this, card identification returns nothing.

```bash
# Test run: 5 pages = ~1250 cards, ~5 min
python scripts/build_card_db.py --pages 5

# Full run: ~20,000 cards, 30-60 min, ~2GB images
python scripts/build_card_db.py
```

- Downloads card images from `https://api.pokemontcg.io/v2/cards`
- Computes pHash (perceptual hash) for each card image
- Stores in `data/cards.db` table `cards` with columns: `card_id, name, set_name, number, image_url, phash`
- Get free API key at pokemontcg.io → 20,000 req/day (vs 1,000/day without key)
- Add to `.env`: `POKEMONTCG_API_KEY=your_key_here`

**Expected result:** `data/cards.db` with ~20,000 rows, `data/card_images/` with ~2GB of card images

### Step 1.2 — Fix main.py Browser Integration ❌ BROKEN

`main.py` currently calls `hls_interceptor.wait_for_url()` but never opens a browser, so it always times out and skips frame extraction.

**Fix needed in `main.py`:**
- Launch `async_playwright()` with Firefox persistent context (`data/session/`)
- Navigate to the stream URL
- Call `hls_interceptor.attach(page)` before navigating
- Run browser + WS client + frame extractor concurrently with `asyncio.gather()`

### Step 1.3 — Configure Discord Bot

```env
DISCORD_BOT_TOKEN=your_token
DISCORD_CHANNEL_ID=your_channel_id
```

Create bot at discord.com/developers → new application → bot → copy token → invite to server.

### Step 1.4 — End-to-End Test

```bash
python main.py https://www.whatnot.com/live/<stream_id> <seller_name>
```

Expected terminal output:
```
[INFO] Stream ID: abc123
[INFO] DB initialized — 20,000 cards loaded
[INFO] Connecting to wss://...auction/socket/websocket
[INFO] Joined: auction:abc123
[INFO] Joined: commerce:abc123
[INFO] [HLS] Found IVS URL: https://....m3u8
[INFO] Frame captured: data/frames/abc123/frame_1234567890.jpg
[EVENT] topic=commerce:abc123 event=auction_ended
[INFO] [AUCTION ENDED] Charizard VMAX -> $47.00 (method=whatnot_image confidence=0.87)
```

---

## Phase 2 — Improve Card Identification Accuracy

### Card Identification Priority (Confirmed)

```
Priority 1: Whatnot listing image (media[0].key from auction_ended payload)
  → Most sellers upload a photo when listing
  → Confidence: ~0.85-0.95
  → Method: download from images.whatnot.com, pHash match against DB

Priority 2: Video frame pHash match (last captured frame before auction_ended)
  → Used when seller lists without an image
  → Confidence: ~0.60-0.80 (depends on lighting, angle, sleeve)
  → Method: OpenCV crop card region → pHash → nearest neighbor in DB

Priority 3: OCR card number from frame (e.g. "025/198")
  → Used as confirmation or fallback
  → Confidence: ~0.85 if number matches DB
  → Method: Tesseract on bottom-right corner of card crop

Priority 4: OCR card name from frame
  → Low accuracy, fonts vary
  → Confidence: ~0.40-0.60
  → Method: Tesseract on top of card crop

Priority 5: No match
  → Save with card_name from WS payload text only
  → card_id = NULL, confidence = 0.0
```

### Step 2.1 — Validate pHash Matching Quality

After building DB, test matching:
```bash
# Capture a test frame, run identification manually
python -c "
import asyncio
from src.vision.card_identifier import CardIdentifier
result = asyncio.run(CardIdentifier().identify(frame_path='data/frames/test.jpg'))
print(result)
"
```

Known issues to tune:
- **Glare/sleeve** → add CLAHE contrast pre-processing in `card_detector.py`
- **Card at angle** → add perspective warp correction
- **Wrong crop** → tune `ASPECT_TOLERANCE` (currently 0.15 in `card_detector.py`)
- **Too many false matches** → lower `HASH_DISTANCE_THRESHOLD` from 15 to 8

### Step 2.2 — OCR Confirmation Layer

When pHash confidence is between 0.5–0.8, run OCR on card number:
- Crop bottom-right 20% of card image
- Run Tesseract with `--psm 7` (single line)
- Regex match `\d{1,3}/\d{1,3}`
- Look up number in DB — if it matches the pHash candidate, boost confidence to 0.95

---

## Phase 3 — Multi-Stream Orchestration

**Goal:** Monitor ALL active Pokemon card streams on Whatnot simultaneously.

### Step 3.1 — Stream Discovery (`src/discovery/stream_finder.py`)

Whatnot has no public streams API. Approach:
- Playwright scrapes `https://www.whatnot.com/explore?category=trading-cards`
- Parses stream cards from DOM, extracts stream IDs + seller usernames
- Filters for Pokemon-related streams (title keyword matching)
- Polls every 60 seconds for new/ended streams

### Step 3.2 — StreamWorker (`src/discovery/stream_manager.py`)

```python
class StreamWorker:
    stream_id: str
    seller: str
    browser_page: Page           # Playwright page for this stream
    hls_interceptor: HLSInterceptor
    frame_extractor: FrameExtractor
    event_handler: AuctionEventHandler
    phoenix_client: PhoenixClient

    async def run(self): ...     # starts all tasks concurrently
    async def stop(self): ...    # tears down cleanly
```

### Step 3.3 — Orchestrator (`src/discovery/orchestrator.py`)

```python
class Orchestrator:
    max_concurrent: int = 20     # browser tabs are expensive
    workers: dict[str, StreamWorker]

    async def run(self):
        while True:
            streams = await stream_finder.get_active_streams()
            self._spawn_new(streams)
            self._stop_ended(streams)
            await asyncio.sleep(60)
```

Resource limits:
- Max 20 concurrent streams
- Prioritize streams with highest bid activity
- Screenshot-only mode for Agora streams (no ffmpeg subprocess)

---

## Phase 4 — Data Dashboard

**Goal:** Web UI showing real-time auction results, price history, seller analytics.

### Step 4.1 — REST API (`src/api/`)

FastAPI server reading from SQLite:
- `GET /auctions` — recent sales with card info
- `GET /cards/{card_id}/history` — price history for specific card
- `GET /sellers/{username}` — seller stats
- `GET /stream/{stream_id}/live` — currently active auctions on a stream

### Step 4.2 — Frontend

Simple dashboard:
- Live feed of recent sales (auto-refreshing)
- Price chart per card over time (Chart.js)
- Seller leaderboard (most volume, avg prices)
- Card search with sale history

### Step 4.3 — PostgreSQL Migration

When running 10+ concurrent streams, SQLite write locks become a bottleneck:
- Migrate schema to PostgreSQL
- Use `asyncpg` for async writes from all stream workers
- Add indexes on `card_id`, `seller_user_id`, `ended_at`

---

## Immediate Action Items (In Order)

| # | Action | Time | Blocking |
|---|---|---|---|
| 1 | Get free API key at pokemontcg.io | 5 min | Step 2 |
| 2 | Add `POKEMONTCG_API_KEY` to `.env` | 1 min | Step 2 |
| 3 | Run `python scripts/build_card_db.py --pages 5` (test) | 5 min | Validation |
| 4 | Run `python scripts/build_card_db.py` (full DB) | 45 min | Identification |
| 5 | Fix `main.py` — open browser + attach HLS interceptor | 30 min | Frame capture |
| 6 | Create Discord bot + add tokens to `.env` | 10 min | Discord output |
| 7 | Test end-to-end on a live Pokemon stream | 30 min | — |
| 8 | Build `stream_finder.py` for auto discovery | 2 hrs | Multi-stream |
| 9 | Build `StreamWorker` + `Orchestrator` | 3 hrs | Scale |
| 10 | Dashboard API + frontend | 1 day | Visibility |

---

## Key Technical Facts

### Pokemon Card Database
- Source: `https://api.pokemontcg.io/v2/cards`
- ~20,000 unique cards across all sets
- Free tier: 1,000 req/day | Authenticated: 20,000 req/day
- Images: ~100KB each → ~2GB total storage
- pHash: 64-bit hash, Hamming distance ≤ 10 = likely same card

### Whatnot Stream Tech
- Most streams: Amazon IVS → HLS `.m3u8` → ffmpeg can grab frames every 30s
- High-concurrency streams: Agora WebRTC → no HLS → must use browser screenshot
- Phoenix WS format: `[join_ref, ref, topic, event, payload]`
- Auth: persistent Firefox session in `data/session/` (manual login once, SMS verification)

### File Layout
```
whatnot-data/
├── main.py                      # entry point (needs browser fix — Phase 1.2)
├── PLAN.md                      # this file
├── scripts/
│   ├── intercept_ws.py          # debug: shows raw WS events in terminal
│   └── build_card_db.py         # one-time: builds card hash DB
├── src/
│   ├── ws/
│   │   ├── phoenix_client.py    # WS client — joins auction: + commerce:
│   │   └── event_handler.py     # maps events → card ID + Discord + DB save
│   ├── vision/
│   │   ├── hls_interceptor.py   # intercepts .m3u8 from browser page requests
│   │   ├── frame_extractor.py   # ffmpeg every 30s + screenshot fallback
│   │   ├── card_detector.py     # OpenCV: crops card region (63:88 ratio)
│   │   ├── card_identifier.py   # 3-tier ID: listing image → pHash → OCR
│   │   └── card_db.py           # SQLite schema + pHash search + save results
│   ├── discovery/               # Phase 3 — not built yet
│   │   ├── stream_finder.py     # Playwright: scrapes active Pokemon streams
│   │   ├── stream_manager.py    # StreamWorker per stream
│   │   └── orchestrator.py      # spawns/stops workers, polls for new streams
│   └── discord/
│       └── bot.py               # Discord bot: bid / sold / stream start posts
└── data/
    ├── cards.db                 # ❌ MISSING — run build_card_db.py
    ├── card_images/             # ❌ MISSING — downloaded by build_card_db.py
    ├── frames/                  # frame captures (one subdir per stream_id)
    └── session/                 # Firefox persistent session (login once)
```
