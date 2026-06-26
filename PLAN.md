# Whatnot Pokemon Data Tracker

## Goal
Monitor all Pokemon card livestreams on Whatnot, capture auction results in real-time, cross-reference with a card database, and track sold prices over time.

---

## Phase 1 — Data Pipeline Validation (Discord Bot)
Before building the full system, validate that data is flowing correctly by piping auction events to a Discord bot.

### What the bot will post
- Stream goes live → `🟢 Stream started: {seller} | {stream_url}`
- Auction starts → `📦 Card up for auction: {card_name} (if detected) | Starting bid: ${amount}`
- Bid placed → `💰 New bid: ${amount} by {username}`
- Auction ends → `🔨 SOLD: ${final_price} | Card: {card_name} | Seller: {seller}`

### Discord Bot Stack
- `discord.py` (Python)
- Webhook or bot token posting to a designated channel

---

## System Architecture

```
Stream Discovery (Playwright + GraphQL intercept)
        │
        ▼
Per-Stream Worker (one per active stream)
    ├── Phoenix WebSocket Client → bid/auction events → Discord Bot + DB
    └── IVS HLS / Agora Screenshot → ffmpeg frame every 30s
                │
                ▼
        Card Recognition (OpenCV + PokemonTCG.io hash match)
                │
                ▼
        SQLite (dev) → Postgres (prod)
                │
                ▼
        Dashboard / Price Trend Queries
```

---

## Components

### 1. Stream Discovery
- Playwright headless browser scrapes Whatnot Pokemon category page
- Intercept GraphQL/REST network requests to extract active stream list
- Yields: `stream_id`, `seller`, `stream_url`, `stream_type` (IVS or Agora)

### 2. Phoenix WebSocket Client
- Connect to `wss://` Whatnot Phoenix channel per stream
- Implement Phoenix protocol: join topic, heartbeat every 30s
- Listen for events:
  - `bid_placed` → bid amount, username
  - auction state updates → auction start, card info
  - `auction_end` / `sold` → final price
- Output: structured auction event objects → Discord + DB

### 3. Video Snapshot Engine
- **IVS streams** → intercept `.m3u8` HLS URL → `ffmpeg` frame every 30s
- **Agora streams** → Playwright headless browser screenshot fallback
- Output: JPEG frame files with timestamp + stream metadata

### 4. Card Recognition
- OpenCV card boundary detection on each frame
- Perceptual hash (`imagehash`) matched against PokemonTCG.io card image DB
- Output: `card_id`, `card_name`, `set`, `confidence_score`

### 5. Database Schema
```sql
cards           (card_id, name, set, number, image_url, image_hash)
streams         (stream_id, seller, url, stream_type, started_at, ended_at)
snapshots       (snapshot_id, stream_id, timestamp, frame_path, matched_card_id, confidence)
auction_results (result_id, stream_id, card_id, sold_price, ended_at, raw_event)
```

### 6. Discord Bot (Phase 1 validation)
- Posts auction lifecycle events to a Discord channel
- Confirms data pipeline is working before DB/dashboard work begins

### 7. Dashboard (Phase 3)
- Price trend per card over time
- Seller analytics
- Market price vs sold price delta

---

## Tech Stack

| Layer | Tool |
|---|---|
| Stream discovery | Python + Playwright |
| WS client | `websockets` + Phoenix protocol |
| Frame capture (IVS) | `ffmpeg` via HLS URL |
| Frame capture (Agora) | Playwright screenshot |
| Card recognition | OpenCV, `imagehash`, PokemonTCG.io API |
| Discord integration | `discord.py` |
| DB | SQLite (dev) → Postgres (prod) |
| Orchestration | Python `asyncio` worker pool |

---

## Phases

### Phase 1 — Discord Validation ← START HERE
- [ ] Reverse engineer Phoenix WS connection for a single stream
- [ ] Build Phoenix WS client (join, heartbeat, event listener)
- [ ] Build Discord bot that posts auction events
- [ ] Confirm `bid_placed`, `auction_end`, `sold` events are received correctly

### Phase 2 — Snapshot + Card Recognition
- [ ] Intercept IVS `.m3u8` URL from stream page
- [ ] Build ffmpeg frame extractor (every 30s)
- [ ] Build card detection + PokemonTCG.io hash matching
- [ ] Link recognized card to auction events

### Phase 3 — Database + Scale
- [ ] SQLite schema + ORM models
- [ ] Swap Discord output for DB writes
- [ ] Stream discovery crawler (multi-stream worker pool)
- [ ] Migrate to Postgres for prod

### Phase 4 — Dashboard
- [ ] Price trend queries per card
- [ ] Seller analytics
- [ ] Market price vs sold price delta
