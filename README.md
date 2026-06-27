# Whatnot Pokemon Card Auction Tracker

Real-time data pipeline that monitors all live Pokemon card auctions on Whatnot. Automatically discovers active streams, captures every auction event via WebSocket, identifies the card being sold using perceptual hashing against a 14,500+ card database, and saves every result — card name, sold price, buyer, bid count, and confidence — to SQLite.

---

## How It Works

```
whatnot.com/explore
       │
       ▼
  StreamFinder (polls every 60s)
       │  discovers new Pokemon card streams
       ▼
  Orchestrator (max 20 concurrent)
       │  spawns one StreamWorker per stream
       ▼
  StreamWorker
  ├── PhoenixClient ──── wss://auction/socket  (auction + commerce topics)
  │                  └── wss://live/socket     (live topic — listing images)
  │
  └── FrameExtractor
       ├── HLS/IVS  → ffmpeg frame every 30s
       └── Agora    → Playwright screenshot every 30s (cropped to video region)
              │
              ▼
         CardIdentifier
         1. Whatnot listing image → pHash match   (most accurate)
         2. Frame crop → OpenCV card detect → pHash match
         3. Frame crop → Tesseract OCR fallback
              │
              ▼
         SQLite  →  auction_results
```

---

## Requirements

- Python 3.10+
- Firefox (via Playwright)
- `ffmpeg` (for HLS streams — `brew install ffmpeg` or `apt install ffmpeg`)
- Tesseract OCR (`brew install tesseract` or `apt install tesseract-ocr`)
- A Whatnot account (free)
- A PokemonTCG.io account for a free API key (optional but recommended for faster DB build)

---

## Installation

```bash
git clone https://github.com/dotkoms/whatnot-data.git
cd whatnot-data

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
playwright install firefox
```

---

## One-Time Setup

These steps are required before the system can run. Do them once locally, then copy the outputs to your server.

### Step 1 — Build the card database

Downloads all ~14,500 Pokemon cards from PokemonTCG.io, computes perceptual hashes (pHash), and stores them in `data/cards.db`. Takes 30–60 minutes.

```bash
# Optional: get a free API key at https://pokemontcg.io for higher rate limits
echo "POKEMONTCG_API_KEY=your_key_here" >> .env

python scripts/build_card_db.py

# Test run with just 5 pages (~1,250 cards):
python scripts/build_card_db.py --pages 5
```

The script resumes automatically if interrupted — it skips cards already in the database.

### Step 2 — Authenticate and capture your auth token

Whatnot has no public API. Authentication works through a browser session. This script opens Firefox, lets you log in manually, then auto-saves the session and JWT auth token to your `.env`.

```bash
python scripts/intercept_ws.py
```

1. A Firefox window opens and navigates to the Whatnot login page
2. Log in manually (including SMS verification code)
3. Once redirected to a stream, the script extracts the JWT from the WebSocket URL and saves it to `.env` automatically
4. Press `Ctrl+C` when done

This creates two things you need:
- `data/session/` — persistent Firefox session (avoids re-authentication)
- `WHATNOT_AUTH_TOKEN=...` in `.env` — JWT for WebSocket channel joins

> **Token expiry**: The JWT typically expires after 24–48 hours. When it expires the system will log a clear warning and tell you to re-run this script.

---

## Configuration

Edit `.env` in the project root:

```env
# Required — captured by running scripts/intercept_ws.py
WHATNOT_AUTH_TOKEN=

# Set to true for headless server deployments (default: true)
HEADLESS=true

# Optional — free API key from pokemontcg.io for faster card DB builds
POKEMONTCG_API_KEY=
```

---

## Running

### Multi-stream mode (auto-discover all Pokemon card streams)

```bash
python3 orchestrate.py
```

The system will:
1. Validate startup — exits immediately with a clear error if auth token or card DB is missing
2. Load 14,500+ card hashes into memory (shared across all workers)
3. Open a Firefox browser context (headless on server)
4. Start `StreamFinder` — polls `whatnot.com/explore?category=trading-cards` every 60 seconds
5. Spawn a `StreamWorker` for each discovered stream (up to 20 concurrent)
6. Each worker self-terminates when its stream ends

### Single-stream mode

```bash
python3 orchestrate.py https://www.whatnot.com/live/<stream_id>
```

### Single-stream legacy mode (simpler, no auto-discovery)

```bash
python3 main.py https://www.whatnot.com/live/<stream_id> <seller_name>
```

### Graceful shutdown

`Ctrl+C` or `SIGTERM` triggers a clean shutdown — browser context closed, in-flight WebSocket connections closed, no data loss.

---

## Viewing Results

```bash
# Last 20 auctions
python3 scripts/view_results.py

# All auctions
python3 scripts/view_results.py --all

# Search by card name
python3 scripts/view_results.py --card charizard
```

Example output:

```
────────────────────────────────────────────────────────────────────────────────────────────────────
TIME                 CARD                                PRICE    BUYER                BIDS   CONF METHOD
────────────────────────────────────────────────────────────────────────────────────────────────────
2026-06-27 14:32     Charizard ex (Scarlet & Violet)    $147.00  trainer_john           12   94% identified
2026-06-27 14:29     Pikachu VMAX                        $23.00  pkmnmaster             5    87% identified
2026-06-27 14:21     Unknown                              $8.00  user_456               2     —  unmatched
────────────────────────────────────────────────────────────────────────────────────────────────────
Showing 3 of 47 results
```

---

## Server Deployment

### Prerequisites

Copy these from your local machine to the server before deploying:

```bash
# Sync card database (~50MB)
scp data/cards.db user@server:/path/to/whatnot-data/data/

# Sync Firefox session (authenticated browser state)
scp -r data/session/ user@server:/path/to/whatnot-data/data/

# Sync .env with your auth token
scp .env user@server:/path/to/whatnot-data/
```

### Install system dependencies on server

```bash
# Ubuntu/Debian
sudo apt install ffmpeg tesseract-ocr

# Install Playwright browsers
playwright install firefox
playwright install-deps firefox
```

### Set headless mode

Ensure your `.env` has:

```env
HEADLESS=true
```

### Run with systemd (recommended)

Create `/etc/systemd/system/whatnot.service`:

```ini
[Unit]
Description=Whatnot Pokemon Card Tracker
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/whatnot-data
ExecStart=/path/to/venv/bin/python3 orchestrate.py
Restart=on-failure
RestartSec=30
EnvironmentFile=/path/to/whatnot-data/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable whatnot
sudo systemctl start whatnot
sudo journalctl -u whatnot -f   # follow logs
```

### Token refresh

When the auth token expires the system logs:

```
⚠️  WHATNOT AUTH TOKEN EXPIRED
   All WebSocket joins are being rejected.
   Run:  python scripts/intercept_ws.py
   Then restart this process.
```

Re-run `scripts/intercept_ws.py` locally, copy the updated `.env` to the server, and restart the service.

---

## Project Structure

```
whatnot-data/
├── orchestrate.py              # Multi-stream entry point
├── main.py                     # Single-stream entry point
├── requirements.txt
├── .env                        # Auth token + config (not committed)
│
├── scripts/
│   ├── intercept_ws.py         # Auth token extractor + WS debugger
│   ├── build_card_db.py        # One-time card database builder
│   └── view_results.py         # CLI results viewer
│
├── src/
│   ├── discovery/
│   │   ├── orchestrator.py     # Manages all StreamWorkers
│   │   ├── stream_finder.py    # Scrapes Whatnot explore page
│   │   └── stream_worker.py    # Per-stream monitor (browser tab + WS)
│   │
│   ├── ws/
│   │   ├── phoenix_client.py   # Phoenix WebSocket client (2 sockets per stream)
│   │   └── event_handler.py    # Maps events to card ID + SQLite writes
│   │
│   └── vision/
│       ├── card_db.py          # SQLite schema + card download loop
│       ├── hash_index.py       # In-memory pHash index (14,500 cards)
│       ├── frame_extractor.py  # ffmpeg HLS frames + Playwright screenshots
│       ├── card_identifier.py  # 3-tier ID pipeline (image → pHash → OCR)
│       ├── card_detector.py    # OpenCV card rectangle detection
│       └── hls_interceptor.py  # Amazon IVS .m3u8 URL interceptor
│
└── data/                       # Created at runtime (not committed)
    ├── cards.db                # SQLite database (cards + auction_results)
    ├── session/                # Firefox persistent session
    ├── frames/                 # Captured stream frames (auto-rotated, max 120/stream)
    └── card_images/            # Card images used during DB build
```

---

## Database Schema

### `cards` table

| Column | Type | Description |
|--------|------|-------------|
| `card_id` | TEXT PK | PokemonTCG.io ID (e.g. `base1-4`) |
| `name` | TEXT | Card name |
| `set_name` | TEXT | Set name (e.g. `Base Set`) |
| `set_id` | TEXT | Set ID |
| `number` | TEXT | Card number within set |
| `image_url` | TEXT | PokemonTCG.io image URL |
| `phash` | TEXT | 64-bit perceptual hash (hex) |
| `created_at` | INTEGER | Unix timestamp |

### `auction_results` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `stream_id` | TEXT | Whatnot stream UUID |
| `listing_id` | TEXT | Whatnot listing ID |
| `card_id` | TEXT | Matched card ID (null if unmatched) |
| `card_name` | TEXT | Card name (identified or from listing) |
| `sold_price_cents` | INTEGER | Final sold price in cents |
| `buyer_username` | TEXT | Winning buyer username |
| `bid_count` | INTEGER | Number of bids |
| `seller_user_id` | TEXT | Seller user ID |
| `image_key` | TEXT | Whatnot CDN image key |
| `confidence` | REAL | Match confidence 0.0–1.0 |
| `frame_path` | TEXT | Path to captured frame used for ID |
| `ended_at` | INTEGER | Unix timestamp of auction end |
| `created_at` | INTEGER | Unix timestamp of DB insert |

---

## Card Identification

Every auction goes through a three-tier identification pipeline:

| Priority | Method | Source | Typical Confidence |
|----------|--------|--------|-------------------|
| 1 | `whatnot_image` | Whatnot listing image from CDN, pHash matched against card DB | 85–99% |
| 2 | `phash` | OpenCV card detection on captured frame, pHash matched | 70–95% |
| 3 | `ocr` | Tesseract reads card name/number text from frame crop | ~40% |

A match requires a Hamming distance ≤ 10 out of 64 bits. Confidence is computed as `1.0 - (distance / threshold)`.

---

## WebSocket Protocol

Whatnot uses the [Elixir Phoenix](https://hexdocs.pm/phoenix/channels.html) WebSocket protocol. Messages are JSON arrays:

```
[join_ref, ref, topic, event, payload]
```

The system connects to two sockets per stream concurrently:

| Socket | Topics joined | Key events |
|--------|--------------|------------|
| `wss://.../auction/socket` | `auction:<stream_id>`, `commerce:<stream_id>` | `bid_placed`, `auction_ended`, `payment_succeeded` |
| `wss://.../live/socket` | `live:<stream_id>` | `item_listed`, `auction_started`, `product_listed` |

The auth JWT is passed in the `phx_join` payload of each topic join. Token expiry is decoded from the JWT at startup and logged.

---

## Troubleshooting

**`❌ WHATNOT_AUTH_TOKEN is not set`**
Run `python scripts/intercept_ws.py`, log in, and the token will be auto-saved to `.env`.

**`❌ Card database not found`**
Run `python scripts/build_card_db.py`. Takes 30–60 minutes. Copy `data/cards.db` to the server.

**`❌ Browser session expired or not found` (server)**
Your `data/session/` directory is missing or stale. Run `python scripts/intercept_ws.py` locally, then copy `data/session/` to the server.

**`⚠️ Join rejected — auth token expired`**
JWT has expired (typically after 24–48 hours). Re-run `python scripts/intercept_ws.py` to capture a fresh token.

**No auction events appearing**
- Confirm `WHATNOT_AUTH_TOKEN` is set and not expired
- Run `python scripts/intercept_ws.py` pointed at a live stream and watch for `[RECV]` lines — if you see `phx_reply` with `status: error`, the token is bad

**`ffmpeg` not found**
Install it: `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Linux).

**Tesseract not found**
Install it: `brew install tesseract` (macOS) or `sudo apt install tesseract-ocr` (Linux).
