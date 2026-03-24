"""
YRFI Alert Bot
- 8am ET: sends daily morning summary of ALL games
- Every 30 min: sends pre-game alert ~1 hour before each game starts
- Scrapes BallparkPal for sim-based YRFI %
- Pulls Pinnacle market odds from OddsBlaze
- Combines both into one Discord alert per game
- Dupe-alert guard: only alerts once per game per day
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

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

MORNING_SUMMARY_SENT_KEY = "morning_summary"


# ── Time helpers ──────────────────────────────────────────────────────────────
def et_now_minutes() -> int:
    """Current ET time as total minutes since midnight. Override with TEST_TIME env var."""
    if test := os.environ.get("TEST_TIME"):
        return int(test)
    now_utc = datetime.now(timezone.utc)
    et = now_utc - timedelta(hours=4)
    return et.hour * 60 + et.minute


def today_et() -> str:
    """Today's date in ET. Override with TEST_DATE env var."""
    if test := os.environ.get("TEST_DATE"):
        return test
    now_utc = datetime.now(timezone.utc)
    et = now_utc - timedelta(hours=4)
    return et.strftime("%Y-%m-%d")


def utc_to_et(utc_str: str) -> datetime | None:
    """Parse ISO UTC string and return ET datetime."""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt - timedelta(hours=4)
    except Exception as e:
        print(f"  Could not parse time '{utc_str}': {e}")
        return None


def utc_to_et_minutes(utc_str: str) -> int | None:
    """Parse ISO UTC string and return ET minutes since midnight."""
    et = utc_to_et(utc_str)
    return et.hour * 60 + et.minute if et else None


def utc_to_et_date(utc_str: str) -> str | None:
    """Parse ISO UTC string and return ET date as YYYY-MM-DD."""
    et = utc_to_et(utc_str)
    return et.strftime("%Y-%m-%d") if et else None


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
        over_price  = int(over_price)
        under_price = int(under_price)
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
            page.goto("https://www.ballparkpal.com/Login.php", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            page.fill("input[type='email']", BPP_EMAIL)
            page.fill("input[type='password']", BPP_PASSWORD)
            page.click("button[type='submit']")
            page.wait_for_timeout(3000)
            print(f"  BPP login: {page.url}")

            # Game sims page
            page.goto(
                f"https://www.ballparkpal.com/Game-Simulations.php?date={date}",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            page.wait_for_timeout(5000)

            body = page.inner_text("body")
            print(f"  BPP body length: {len(body)}")

            if len(body) < 300:
                print("  No BPP game data for this date")
                return games

            # BallparkPal uses .summaryDescriptionContainer for each game card
            blocks = page.query_selector_all(".summaryDescriptionContainer")
            print(f"  Found {len(blocks)} game cards")

            for block in blocks:
                try:
                    away_divs = block.query_selector_all(".awayTeam")
                    home_divs = block.query_selector_all(".homeTeam")
                    yrfi_el   = block.query_selector(".yrfi")
                    time_el   = block.query_selector(".atSymbol")

                    # Team names at index 1, pitchers at 2, win% at 4
                    away    = away_divs[1].inner_text().strip() if len(away_divs) > 1 else None
                    home    = home_divs[1].inner_text().strip() if len(home_divs) > 1 else None
                    away_p  = away_divs[2].inner_text().strip() if len(away_divs) > 2 else None
                    home_p  = home_divs[2].inner_text().strip() if len(home_divs) > 2 else None
                    away_win_raw = away_divs[4].inner_text().strip() if len(away_divs) > 4 else None
                    home_win_raw = home_divs[4].inner_text().strip() if len(home_divs) > 4 else None

                    # Parse YRFI: "YRFI: 40.6% (+146)"
                    yrfi_text = yrfi_el.inner_text().strip() if yrfi_el else ""
                    yrfi_m    = re.search(r'(\d+\.?\d*)%', yrfi_text)
                    odds_m    = re.search(r'([+-]\d{3,4})', yrfi_text)
                    yrfi_pct  = float(yrfi_m.group(1)) if yrfi_m else None
                    yrfi_odds = int(odds_m.group(1)) if odds_m else None

                    # Parse win %: "(-120) 54.5%" or "45.5% (+120)"
                    away_win_m = re.search(r'(\d+\.?\d*)%', away_win_raw or "")
                    home_win_m = re.search(r'(\d+\.?\d*)%', home_win_raw or "")

                    if away and home and yrfi_pct:
                        games.append({
                            "away":         away,
                            "home":         home,
                            "yrfi_pct":     yrfi_pct,
                            "yrfi_odds":    yrfi_odds,
                            "away_win_pct": float(away_win_m.group(1)) if away_win_m else None,
                            "home_win_pct": float(home_win_m.group(1)) if home_win_m else None,
                            "away_pitcher": away_p,
                            "home_pitcher": home_p,
                        })
                        print(f"    {away} @ {home}  YRFI: {yrfi_pct}% ({yrfi_odds})")
                except Exception as e:
                    print(f"  Block parse error: {e}")
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


# ── Discord: single game alert ────────────────────────────────────────────────
def send_game_alert(away, home, pin_pct, over_odds, under_odds,
                    bpp_pct=None, bpp_odds=None,
                    away_win=None, home_win=None,
                    away_pitcher=None, home_pitcher=None,
                    title_prefix="🔔 First Pitch ~1 Hour"):

    best_pct = bpp_pct or pin_pct or 0
    color = 0x22c55e if best_pct >= 65 else 0xf59e0b

    fields = []
    if bpp_pct is not None:
        odds_str = f"  (fair: {bpp_odds:+d})" if bpp_odds else ""
        fields.append({"name": "📊 BallparkPal (sim)",  "value": f"**{bpp_pct}%**{odds_str}", "inline": True})
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
            "title": f"{title_prefix}: {away} @ {home}",
            "fields": fields,
            "color": color,
            "footer": {"text": "BallparkPal sim + OddsBlaze Pinnacle"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    r = requests.post(DISCORD_WEBHOOK, json=embed, timeout=10)
    r.raise_for_status()


# ── Discord: morning summary ──────────────────────────────────────────────────
def send_morning_summary(odds_games: list[dict], bpp_games: list[dict]):
    """Send one Discord message summarising all of today's games."""
    if not odds_games:
        return

    lines = []
    for g in sorted(odds_games, key=lambda x: x["start"]):
        et_min = utc_to_et_minutes(g["start"])
        time_str = f"{et_min//60}:{et_min%60:02d} ET" if et_min else "TBD"

        # Match BPP
        bpp = None
        for b in bpp_games:
            a_last = g["away"].split()[-1].lower()
            if a_last in b.get("away", "").lower():
                bpp = b
                break

        bpp_str = f"  BPP: {bpp['yrfi_pct']}%" if bpp and bpp.get("yrfi_pct") else ""
        pin_str = f"  PIN: {g['yrfi_pct']}% ({g['over_odds']:+d}/{g['under_odds']:+d})"
        lines.append(f"**{g['away']} @ {g['home']}** — {time_str}\n{pin_str}{bpp_str}")

    description = "\n\n".join(lines)
    embed = {
        "embeds": [{
            "title": f"⚾ Today's YRFI Slate — {today_et()}",
            "description": description,
            "color": 0x3b82f6,
            "footer": {"text": "BallparkPal sim + OddsBlaze Pinnacle"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    r = requests.post(DISCORD_WEBHOOK, json=embed, timeout=10)
    r.raise_for_status()
    print("  ✓ Morning summary sent")


# ── Dupe guard: morning summary ───────────────────────────────────────────────
def morning_summary_sent_today() -> bool:
    today = today_et()
    result = (
        supabase.table("yrfi_alerts_sent")
        .select("game_id")
        .eq("game_id", f"morning_summary_{today}")
        .limit(1)
        .execute()
    )
    return len(result.data) > 0


def mark_morning_summary_sent():
    today = today_et()
    supabase.table("yrfi_alerts_sent").insert({
        "game_id":    f"morning_summary_{today}",
        "matchup":    "morning_summary",
        "alerted_at": datetime.now(timezone.utc).isoformat(),
    }).execute()


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    now_min = et_now_minutes()
    today   = today_et()
    is_morning = 8 * 60 <= now_min < 8 * 60 + 30   # 8:00–8:29 ET

    print(f"\n[{datetime.now(timezone.utc).isoformat()}] YRFI Bot")
    print(f"  ET: {now_min//60}:{now_min%60:02d}  |  Morning mode: {is_morning}")

    # 1. Always fetch + upsert OddsBlaze
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

    # Filter to only TODAY's games in ET
    odds_games = [g for g in odds_games if utc_to_et_date(g["start"]) == today]
    print(f"  {len(odds_games)} games on {today} ET")

    if not odds_games:
        print("  No games today. Done.")
        return

    # 2. Scrape BallparkPal (always needed for both modes)
    print("\n→ Scraping BallparkPal...")
    try:
        bpp_games = scrape_ballparkpal(today)
    except Exception as e:
        print(f"  BPP error: {e}")
        bpp_games = []

    # ── Morning summary ──
    if is_morning:
        if morning_summary_sent_today():
            print("  Morning summary already sent today.")
        else:
            send_morning_summary(odds_games, bpp_games)
            mark_morning_summary_sent()
        return

    # ── Pre-game alerts (~1 hour before each game) ──
    win_lo = now_min + 50
    win_hi = now_min + 80
    print(f"\n→ Checking pre-game window: {win_lo//60}:{win_lo%60:02d}–{win_hi//60}:{win_hi%60:02d} ET")

    games_in_window = [
        g for g in odds_games
        if (et_min := utc_to_et_minutes(g["start"])) is not None
        and win_lo <= et_min <= win_hi
    ]

    alerted = 0
    for g in games_in_window:
        if already_alerted(g["game_id"]):
            print(f"  Already alerted: {g['away']} @ {g['home']}")
            continue

        bpp = None
        for b in bpp_games:
            a_last = g["away"].split()[-1].lower()
            if a_last in b.get("away", "").lower():
                bpp = b
                break

        send_game_alert(
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

    if not games_in_window:
        print("  No games in window.")
    print(f"\nDone. {alerted} alert(s) sent.\n")


if __name__ == "__main__":
    run()
