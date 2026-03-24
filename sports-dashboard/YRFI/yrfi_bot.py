"""
YRFI Alert Bot
- Scrapes BallparkPal for sim-based YRFI %
- Pulls Pinnacle market odds from OddsBlaze
- Combines both into one Discord alert
- Dupe-alert guard: only alerts once per game per day
- Runs every 30 min via Railway cron
"""

import os
import re
import json
import subprocess
import requests
from supabase import create_client
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

# ── Config ────────────────────────────────────────────────────────────────────
ODDS_KEY        = os.environ["ODDSBLAZE_KEY"]
SUPABASE_URL    = os.environ["SUPABASE_URL"]
SUPABASE_KEY    = os.environ["SUPABASE_KEY"]
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
BPP_EMAIL       = os.environ["BPP_EMAIL"]
BPP_PASSWORD    = os.environ["BPP_PASSWORD"]
YRFI_THRESHOLD  = float(os.environ.get("YRFI_THRESHOLD", "60"))

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Time helpers ──────────────────────────────────────────────────────────────
def et_now_minutes() -> int:
    """Current ET time as total minutes since midnight."""
    now_utc = datetime.now(timezone.utc)
    et = now_utc - timedelta(hours=4)  # EDT (UTC-4); adjust to -5 in winter
    return et.hour * 60 + et.minute


def today_et() -> str:
    now_utc = datetime.now(timezone.utc)
    et = now_utc - timedelta(hours=4)
    return et.strftime("%Y-%m-%d")


def utc_to_et_minutes(utc_str: str) -> int | None:
    """Parse ISO UTC string and return ET minutes since midnight."""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        et = dt - timedelta(hours=4)
        return et.hour * 60 + et.minute
    except Exception as e:
        print(f"  Could not parse time '{utc_str}': {e}")
        return None


# ── OddsBlaze ─────────────────────────────────────────────────────────────────
def american_to_prob(price: int) -> float:
    if price > 0:
        return 100 / (price + 100)
    return abs(price) / (abs(price) + 100)


def fair_yrfi_pct(over_price: int, under_price: int) -> float:
    over_imp  = american_to_prob(over_price)
    under_imp = american_to_prob(under_price)
    return round((over_imp / (over_imp + under_imp)) * 100, 1)


def fetch_oddsblaze() -> list[dict]:
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
    results = []
    for ev in resp.json().get("events", []):
        odds_map    = {o["name"]: o["price"] for o in ev.get("odds", [])}
        over_price  = odds_map.get("Over 0.5")
        under_price = odds_map.get("Under 0.5")
        if over_price is None or under_price is None:
            continue
        results.append({
            "game_id":    ev["id"],
            "away":       ev["teams"]["away"]["name"],
            "home":       ev["teams"]["home"]["name"],
            "start":      ev["date"],
            "yrfi_pct":   fair_yrfi_pct(over_price, under_price),
            "over_odds":  over_price,
            "under_odds": under_price,
        })
    return results


# ── BallparkPal scraper ───────────────────────────────────────────────────────
def scrape_ballparkpal(date: str) -> list[dict]:
    """
    Log into BallparkPal, scrape game sim data.
    Returns list of dicts: away, home, yrfi_pct, yrfi_odds,
    away_win_pct, home_win_pct, away_pitcher, home_pitcher
    """
    games = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()

        try:
            # Login
            page.goto("https://www.ballparkpal.com/Login.php", wait_until="networkidle", timeout=30000)
            page.fill("input[type='email']", BPP_EMAIL)
            page.fill("input[type='password']", BPP_PASSWORD)
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle", timeout=15000)
            print(f"  BPP login: {page.url}")

            # Game sims page
            page.goto(
                f"https://www.ballparkpal.com/Game-Simulations.php?date={date}",
                wait_until="networkidle",
                timeout=30000,
            )
            page.wait_for_timeout(4000)

            body = page.inner_text("body")
            print(f"  BPP body length: {len(body)}")

            if len(body) < 300:
                print("  No BPP game data for this date")
                return games

            # Try to find game cards
            selectors = [
                ".game-card", ".sim-card", "[class*='game-row']",
                "[class*='GameCard']", "[class*='game_card']",
                "table tr", ".container .row > div",
            ]
            blocks = []
            for sel in selectors:
                blocks = page.query_selector_all(sel)
                if len(blocks) > 2:
                    print(f"  Found {len(blocks)} blocks with selector '{sel}'")
                    break

            for block in blocks:
                try:
                    text = block.inner_text().strip()
                    if len(text) < 20:
                        continue

                    # YRFI %
                    yrfi_m = re.search(r'(?:YRFI|1st)[:\s]+(\d{2,3}\.?\d*)%', text, re.I)
                    if not yrfi_m:
                        yrfi_m = re.search(r'(\d{2,3}\.\d)%', text)
                    yrfi_pct = float(yrfi_m.group(1)) if yrfi_m else None

                    # Odds
                    odds_m = re.search(r'([+-]\d{3,4})', text)
                    yrfi_odds = int(odds_m.group(1)) if odds_m else None

                    # Win %
                    win_pcts = re.findall(r'(\d{2,3}\.\d)%', text)

                    # Pitchers (look for "P. Name vs P. Name" or "Pitcher: X")
                    pitcher_m = re.search(r'([A-Z][a-z]+ [A-Z][a-z]+)\s+vs\.?\s+([A-Z][a-z]+ [A-Z][a-z]+)', text)
                    away_p = pitcher_m.group(1) if pitcher_m else None
                    home_p = pitcher_m.group(2) if pitcher_m else None

                    # Teams — look for known team name patterns
                    team_m = re.search(r'([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s+@\s+([A-Z][a-z]+(?: [A-Z][a-z]+)?)', text)
                    away = team_m.group(1) if team_m else None
                    home = team_m.group(2) if team_m else None

                    if yrfi_pct and away and home:
                        games.append({
                            "away":          away,
                            "home":          home,
                            "yrfi_pct":      yrfi_pct,
                            "yrfi_odds":     yrfi_odds,
                            "away_win_pct":  float(win_pcts[0]) if len(win_pcts) > 0 else None,
                            "home_win_pct":  float(win_pcts[1]) if len(win_pcts) > 1 else None,
                            "away_pitcher":  away_p,
                            "home_pitcher":  home_p,
                        })
                except Exception as e:
                    continue

        except Exception as e:
            print(f"  BPP scrape error: {e}")
        finally:
            browser.close()

    print(f"  BPP scraped {len(games)} games")
    return games


# ── Dupe guard ────────────────────────────────────────────────────────────────
def already_alerted(game_id: str) -> bool:
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


def mark_alerted(game_id: str, matchup: str):
    supabase.table("yrfi_alerts_sent").insert({
        "game_id":    game_id,
        "matchup":    matchup,
        "alerted_at": datetime.now(timezone.utc).isoformat(),
    }).execute()


# ── Discord ───────────────────────────────────────────────────────────────────
def send_discord(away, home, pin_pct, over_odds, under_odds,
                 bpp_pct=None, bpp_odds=None,
                 away_win=None, home_win=None,
                 away_pitcher=None, home_pitcher=None):

    best_pct = bpp_pct or pin_pct or 0
    color = 0x22c55e if best_pct >= 65 else 0xf59e0b

    fields = []

    if bpp_pct is not None:
        odds_str = f"  (fair: {bpp_odds:+d})" if bpp_odds else ""
        fields.append({"name": "📊 BallparkPal (sim)",   "value": f"**{bpp_pct}%**{odds_str}", "inline": True})

    if pin_pct is not None:
        fields.append({"name": "📈 Pinnacle (market)", "value": f"**{pin_pct}%**  ({over_odds:+d} / {under_odds:+d})", "inline": True})

    if bpp_pct and pin_pct:
        edge = round(bpp_pct - pin_pct, 1)
        if abs(edge) >= 3:
            sign = "+" if edge > 0 else ""
            fields.append({"name": "⚡ Edge", "value": f"{sign}{edge}% vs market", "inline": True})

    if away_win and home_win:
        fields.append({"name": "🏆 Win %", "value": f"{away} {away_win}% / {home} {home_win}%", "inline": False})

    if away_pitcher or home_pitcher:
        fields.append({"name": "⚾ Starters", "value": f"{away_pitcher or '?'} vs {home_pitcher or '?'}", "inline": False})

    embed = {
        "embeds": [{
            "title": f"🔔 First Pitch ~1 Hour: {away} @ {home}",
            "fields": fields,
            "color": color,
            "footer": {"text": "BallparkPal sim + OddsBlaze Pinnacle"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    r = requests.post(DISCORD_WEBHOOK, json=embed, timeout=10)
    r.raise_for_status()


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    now_min = et_now_minutes()
    today   = today_et()
    win_lo  = now_min + 50
    win_hi  = now_min + 80
    print(f"\n[{datetime.now(timezone.utc).isoformat()}] YRFI Bot")
    print(f"  ET: {now_min//60}:{now_min%60:02d}  |  Window: {win_lo//60}:{win_lo%60:02d}–{win_hi//60}:{win_hi%60:02d}")

    # 1. OddsBlaze
    print("\n→ Fetching OddsBlaze...")
    try:
        odds_games = fetch_oddsblaze()
        print(f"  {len(odds_games)} games")
        if odds_games:
            rows = [{
                "game_id": g["game_id"], "away": g["away"], "home": g["home"],
                "start_time": g["start"], "yrfi_pct": g["yrfi_pct"],
                "over_odds": g["over_odds"], "under_odds": g["under_odds"],
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            } for g in odds_games]
            supabase.table("yrfi_odds").upsert(rows, on_conflict="game_id").execute()
    except Exception as e:
        print(f"  OddsBlaze error: {e}")
        odds_games = []

    # Check if any games are in window before scraping BPP
    games_in_window = [
        g for g in odds_games
        if (et_min := utc_to_et_minutes(g["start"])) is not None
        and win_lo <= et_min <= win_hi
    ]

    if not games_in_window:
        print(f"\n  No games in window. Done.")
        return

    # 2. BallparkPal (only if needed)
    print(f"\n→ Scraping BallparkPal ({len(games_in_window)} game(s) in window)...")
    try:
        bpp_games = scrape_ballparkpal(today)
    except Exception as e:
        print(f"  BPP error: {e}")
        bpp_games = []

    # 3. Send alerts
    alerted = 0
    for g in games_in_window:
        if already_alerted(g["game_id"]):
            print(f"  Already alerted: {g['away']} @ {g['home']}")
            continue

        # Match BPP data by team name
        bpp = None
        for b in bpp_games:
            a_last = g["away"].split()[-1].lower()
            h_last = g["home"].split()[-1].lower()
            if a_last in b.get("away", "").lower() or h_last in b.get("home", "").lower():
                bpp = b
                break

        send_discord(
            away         = g["away"],
            home         = g["home"],
            pin_pct      = g["yrfi_pct"],
            over_odds    = g["over_odds"],
            under_odds   = g["under_odds"],
            bpp_pct      = bpp["yrfi_pct"] if bpp else None,
            bpp_odds     = bpp["yrfi_odds"] if bpp else None,
            away_win     = bpp["away_win_pct"] if bpp else None,
            home_win     = bpp["home_win_pct"] if bpp else None,
            away_pitcher = bpp["away_pitcher"] if bpp else None,
            home_pitcher = bpp["home_pitcher"] if bpp else None,
        )
        mark_alerted(g["game_id"], f"{g['away']} @ {g['home']}")
        print(f"  ✓ Alert sent: {g['away']} @ {g['home']}")
        alerted += 1

    print(f"\nDone. {alerted} alert(s) sent.\n")


if __name__ == "__main__":
    run()
