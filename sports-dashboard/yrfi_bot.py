"""
YRFI Alert Bot
- Pulls MLB 1st inning total runs odds from OddsBlaze (Pinnacle)
- Stores every game in Supabase (upserts so no dupes)
- Sends Discord alert when YRFI % >= threshold
- Dupe-alert guard: only alerts once per game_id per day
"""

import os
import requests
from supabase import create_client
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
ODDS_KEY        = os.environ["ODDSBLAZE_KEY"]
SUPABASE_URL    = os.environ["SUPABASE_URL"]
SUPABASE_KEY    = os.environ["SUPABASE_KEY"]
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
YRFI_THRESHOLD  = float(os.environ.get("YRFI_THRESHOLD", "60"))  # default 60%

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Helpers ───────────────────────────────────────────────────────────────────
def american_to_prob(price: int) -> float:
    """Convert American odds to raw implied probability."""
    if price > 0:
        return 100 / (price + 100)
    return abs(price) / (abs(price) + 100)


def fair_yrfi_pct(over_price: int, under_price: int) -> float:
    """Remove vig and return fair YRFI % (over 0.5 runs)."""
    over_imp  = american_to_prob(over_price)
    under_imp = american_to_prob(under_price)
    total     = over_imp + under_imp
    return round((over_imp / total) * 100, 1)


def already_alerted(game_id: str) -> bool:
    """Check Supabase to see if we already sent a Discord alert for this game today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = (
        supabase.table("yrfi_alerts_sent")
        .select("game_id")
        .eq("game_id", game_id)
        .gte("alerted_at", f"{today}T00:00:00Z")
        .limit(1)
        .execute()
    )
    return len(result.data) > 0


def mark_alerted(game_id: str, away: str, home: str):
    """Record that we sent an alert for this game."""
    supabase.table("yrfi_alerts_sent").insert({
        "game_id":    game_id,
        "matchup":    f"{away} @ {home}",
        "alerted_at": datetime.now(timezone.utc).isoformat(),
    }).execute()


def send_discord(away: str, home: str, yrfi_pct: float, over_price: int, under_price: int, start_utc: str):
    """Send formatted Discord embed alert."""
    color = 0x22c55e if yrfi_pct >= 65 else 0xf59e0b

    embed = {
        "embeds": [{
            "title": f"⚾ YRFI Alert — {away} @ {home}",
            "fields": [
                {"name": "YRFI %",      "value": f"**{yrfi_pct}%**", "inline": True},
                {"name": "Over 0.5",    "value": f"{over_price:+d}", "inline": True},
                {"name": "Under 0.5",   "value": f"{under_price:+d}","inline": True},
                {"name": "First Pitch", "value": start_utc,          "inline": False},
            ],
            "color": color,
            "footer": {"text": "OddsBlaze · Pinnacle · No-vig probability"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    r = requests.post(DISCORD_WEBHOOK, json=embed, timeout=10)
    r.raise_for_status()


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Fetching OddsBlaze...")

    resp = requests.get(
        "https://odds.oddsblaze.com/",
        params={
            "key":        ODDS_KEY,
            "sportsbook": "pinnacle",
            "league":     "mlb",
            "market":     "1st-inning-total-runs",
        },
        timeout=15,
    )
    resp.raise_for_status()
    events = resp.json().get("events", [])
    print(f"  Found {len(events)} MLB games")

    if not events:
        print("  No games — nothing to do.")
        return

    upsert_rows = []

    for ev in events:
        game_id = ev["id"]
        away    = ev["teams"]["away"]["name"]
        home    = ev["teams"]["home"]["name"]
        start   = ev["date"]

        odds_map    = {o["name"]: o["price"] for o in ev.get("odds", [])}
        over_price  = odds_map.get("Over 0.5")
        under_price = odds_map.get("Under 0.5")

        if over_price is None or under_price is None:
            print(f"  Skipping {away} @ {home} — missing odds")
            continue

        yrfi_pct = fair_yrfi_pct(over_price, under_price)
        print(f"  {away:25s} @ {home:25s}  YRFI: {yrfi_pct}%  ({over_price:+d} / {under_price:+d})")

        upsert_rows.append({
            "game_id":    game_id,
            "away":       away,
            "home":       home,
            "start_time": start,
            "yrfi_pct":   yrfi_pct,
            "over_odds":  over_price,
            "under_odds": under_price,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

        if yrfi_pct >= YRFI_THRESHOLD:
            if already_alerted(game_id):
                print(f"    → Already alerted today, skipping Discord")
            else:
                send_discord(away, home, yrfi_pct, over_price, under_price, start)
                mark_alerted(game_id, away, home)
                print(f"    → Discord alert sent!")

    if upsert_rows:
        supabase.table("yrfi_odds").upsert(upsert_rows, on_conflict="game_id").execute()
        print(f"  Upserted {len(upsert_rows)} rows to Supabase")

    print("Done.\n")


if __name__ == "__main__":
    run()
