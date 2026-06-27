"""
View auction results from the database.

Usage:
    python3 scripts/view_results.py          # last 20 results
    python3 scripts/view_results.py --all    # all results
    python3 scripts/view_results.py --card charizard  # search by card name
"""

import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path(__file__).parent.parent / "data" / "cards.db"


def view(limit=20, card_filter=None):
    if not DB_PATH.exists():
        print("No database found. Run scripts/build_card_db.py first.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM auction_results"
    params = []
    if card_filter:
        query += " WHERE card_name LIKE ?"
        params.append(f"%{card_filter}%")
    query += " ORDER BY ended_at DESC"
    if limit:
        query += f" LIMIT {limit}"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        print("No auction results yet.")
        return

    print(f"\n{'─'*100}")
    print(f"{'TIME':<20} {'CARD':<35} {'PRICE':>8} {'BUYER':<20} {'BIDS':>5} {'CONF':>6} {'METHOD':<15}")
    print(f"{'─'*100}")

    for row in rows:
        ts = datetime.fromtimestamp(row["ended_at"]).strftime("%Y-%m-%d %H:%M")
        price = f"${row['sold_price_cents']/100:.2f}"
        conf = f"{row['confidence']:.0%}" if row["confidence"] else "—"
        print(
            f"{ts:<20} {(row['card_name'] or 'Unknown')[:34]:<35} "
            f"{price:>8} {(row['buyer_username'] or '—')[:19]:<20} "
            f"{row['bid_count']:>5} {conf:>6} {row['confidence'] and 'identified' or 'unmatched':<15}"
        )

    total = conn.execute("SELECT COUNT(*) FROM auction_results").fetchone()[0] if not card_filter else len(rows)
    print(f"{'─'*100}")
    print(f"Showing {len(rows)} results\n")


if __name__ == "__main__":
    limit = 20
    card_filter = None

    if "--all" in sys.argv:
        limit = None
    if "--card" in sys.argv:
        idx = sys.argv.index("--card")
        card_filter = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None

    view(limit=limit, card_filter=card_filter)
