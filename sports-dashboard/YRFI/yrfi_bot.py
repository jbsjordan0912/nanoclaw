"""
NRFI Alert Bot (multi-book)
- 8am ET: sends daily morning summary of ALL games with NRFI % from every available book
- Every 30 min: sends pre-game alert ~1 hour before each game starts
- Scrapes BallparkPal for sim-based NRFI % (100 - YRFI%)
- Pulls 1st inning odds from all available sportsbooks via OddsBlaze
- De-vigs each book's line independently, shows all side by side
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
DISCORD_WEBHOOK   = os.environ["DISCORD_WEBHOOK"]
DISCORD_WEBHOOK_2 = os.environ.get("DISCORD_WEBHOOK_2", "")
BPP_EMAIL       = os.environ["BPP_EMAIL"]
BPP_PASSWORD    = os.environ["BPP_PASSWORD"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Books to check, in priority order (sharpest first for consensus)
SPORTSBOOKS = ["pinnacle", "caesars", "fanduel", "draftkings", "betmgm", "bet365", "bovada"]
BOOK_LABELS = {
    "pinnacle": "PIN", "caesars": "CZR", "fanduel": "FD",
    "draftkings": "DK", "betmgm": "MGM", "bet365": "365", "bovada": "BOV",
}


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


# ── OddsBlaze (multi-book) ───────────────────────────────────────────────────
def american_to_prob(price: int) -> float:
    if price > 0:
        return 100 / (price + 100)
    return abs(price) / (abs(price) + 100)


def fair_nrfi_pct(over_price: int, under_price: int) -> float:
    """De-vig and return fair NRFI % (Under 0.5 = no run first inning)."""
    over_imp  = american_to_prob(over_price)
    under_imp = american_to_prob(under_price)
    return round((under_imp / (over_imp + under_imp)) * 100, 1)


def fetch_all_books() -> dict:
    """
    Fetch 1st inning odds from all available sportsbooks.
    Returns dict keyed by (away_team, home_team) with structure:
    {
        "game_id": str, "away": str, "home": str, "start": str,
        "books": { "pinnacle": {"nrfi_pct": float, "over": int, "under": int}, ... }
    }
    """
    games = {}

    for book in SPORTSBOOKS:
        try:
            resp = requests.get(
                "https://odds.oddsblaze.com/",
                params={
                    "key":        ODDS_KEY,
                    "sportsbook": book,
                    "league":     "mlb",
                    "market":     "1st-inning-total-runs",
                },
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json().get("events", [])
            if not events:
                continue
            print(f"  {book}: {len(events)} games")

            for ev in events:
                odds_map    = {o["name"]: o["price"] for o in ev.get("odds", [])}
                over_price  = odds_map.get("Over 0.5")
                under_price = odds_map.get("Under 0.5")
                if over_price is None or under_price is None:
                    continue
                over_price  = int(over_price)
                under_price = int(under_price)

                away = ev["teams"]["away"]["name"]
                home = ev["teams"]["home"]["name"]
                key  = (away, home)

                if key not in games:
                    games[key] = {
                        "game_id": ev["id"],
                        "away":    away,
                        "home":    home,
                        "start":   ev["date"],
                        "books":   {},
                    }

                games[key]["books"][book] = {
                    "nrfi_pct": fair_nrfi_pct(over_price, under_price),
                    "over":     over_price,
                    "under":    under_price,
                }

        except Exception as e:
            print(f"  {book} error: {e}")

    return games


def best_nrfi_pct(game: dict) -> float | None:
    """Get the best NRFI % — prefer Pinnacle, then first available sharp book."""
    books = game.get("books", {})
    for book in SPORTSBOOKS:
        if book in books:
            return books[book]["nrfi_pct"]
    return None


# ── BallparkPal scraper ───────────────────────────────────────────────────────
def scrape_ballparkpal(date: str) -> list[dict]:
    """
    Log into BallparkPal, scrape game sim data.
    Returns NRFI % (100 - YRFI%) along with other game data.
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

                    # Team names at index 1, pitchers at 2, win% at 4
                    away    = away_divs[1].inner_text().strip() if len(away_divs) > 1 else None
                    home    = home_divs[1].inner_text().strip() if len(home_divs) > 1 else None
                    away_p  = away_divs[2].inner_text().strip() if len(away_divs) > 2 else None
                    home_p  = home_divs[2].inner_text().strip() if len(home_divs) > 2 else None
                    away_win_raw = away_divs[4].inner_text().strip() if len(away_divs) > 4 else None
                    home_win_raw = home_divs[4].inner_text().strip() if len(home_divs) > 4 else None

                    # Parse YRFI: "YRFI: 40.6% (+146)" → convert to NRFI
                    yrfi_text = yrfi_el.inner_text().strip() if yrfi_el else ""
                    yrfi_m    = re.search(r'(\d+\.?\d*)%', yrfi_text)
                    odds_m    = re.search(r'([+-]\d{3,4})', yrfi_text)
                    yrfi_pct  = float(yrfi_m.group(1)) if yrfi_m else None
                    nrfi_pct  = round(100 - yrfi_pct, 1) if yrfi_pct is not None else None
                    yrfi_odds = int(odds_m.group(1)) if odds_m else None

                    # Parse win %
                    away_win_m = re.search(r'(\d+\.?\d*)%', away_win_raw or "")
                    home_win_m = re.search(r'(\d+\.?\d*)%', home_win_raw or "")

                    if away and home and nrfi_pct is not None:
                        games.append({
                            "away":         away,
                            "home":         home,
                            "nrfi_pct":     nrfi_pct,
                            "yrfi_odds":    yrfi_odds,
                            "away_win_pct": float(away_win_m.group(1)) if away_win_m else None,
                            "home_win_pct": float(home_win_m.group(1)) if home_win_m else None,
                            "away_pitcher": away_p,
                            "home_pitcher": home_p,
                        })
                        print(f"    {away} @ {home}  NRFI: {nrfi_pct}%")
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
def send_game_alert(away, home, books, bpp_nrfi=None,
                    away_win=None, home_win=None,
                    away_pitcher=None, home_pitcher=None,
                    title_prefix="🔔 First Pitch ~1 Hour"):

    # Use best available NRFI %
    best_pct = bpp_nrfi
    if best_pct is None:
        for book in SPORTSBOOKS:
            if book in books:
                best_pct = books[book]["nrfi_pct"]
                break
    best_pct = best_pct or 0
    color = 0x22c55e if best_pct >= 55 else 0xf59e0b if best_pct >= 45 else 0xef4444

    fields = []

    # BallparkPal sim
    if bpp_nrfi is not None:
        fields.append({"name": "📊 BPP Sim", "value": f"**{bpp_nrfi}%** NRFI", "inline": True})

    # All books side by side
    book_lines = []
    for book in SPORTSBOOKS:
        if book in books:
            b = books[book]
            label = BOOK_LABELS.get(book, book.upper())
            book_lines.append(f"**{label}**: {b['nrfi_pct']}% ({b['under']:+d}/{b['over']:+d})")
    if book_lines:
        fields.append({"name": "📈 Books (NRFI%)", "value": "\n".join(book_lines), "inline": False})

    # Edge: BPP vs sharpest book
    if bpp_nrfi and books:
        sharp_pct = None
        for book in SPORTSBOOKS:
            if book in books:
                sharp_pct = books[book]["nrfi_pct"]
                break
        if sharp_pct:
            edge = round(bpp_nrfi - sharp_pct, 1)
            if abs(edge) >= 3:
                sign = "+" if edge > 0 else ""
                fields.append({"name": "⚡ Edge (sim vs market)", "value": f"{sign}{edge}%", "inline": True})

    if away_win and home_win:
        fields.append({"name": "🏆 Win %", "value": f"{away} {away_win}% / {home} {home_win}%", "inline": False})
    if away_pitcher or home_pitcher:
        fields.append({"name": "⚾ Starters", "value": f"{away_pitcher or '?'} vs {home_pitcher or '?'}", "inline": False})

    books_used = ", ".join(BOOK_LABELS.get(b, b) for b in SPORTSBOOKS if b in books)
    embed = {
        "embeds": [{
            "title": f"{title_prefix}: {away} @ {home}",
            "fields": fields,
            "color": color,
            "footer": {"text": f"BPP sim + OddsBlaze ({books_used or 'no books'})"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    r = requests.post(DISCORD_WEBHOOK, json=embed, timeout=10)
    r.raise_for_status()


# ── Discord: morning summary ──────────────────────────────────────────────────
def send_morning_summary(all_games: dict, bpp_games: list[dict]):
    """Send one Discord message summarising all of today's NRFI numbers."""
    if not all_games:
        return

    # Sort by start time
    sorted_games = sorted(all_games.values(), key=lambda x: x["start"])

    lines = []
    for g in sorted_games:
        et_min = utc_to_et_minutes(g["start"])
        time_str = f"{et_min//60}:{et_min%60:02d} ET" if et_min else "TBD"

        # Match BPP by team name
        bpp = None
        for b in bpp_games:
            a_last = g["away"].split()[-1].lower()
            if a_last in b.get("away", "").lower():
                bpp = b
                break

        # Build book line: "PIN 54.2% | FD 53.8% | CZR 55.0%"
        book_parts = []
        for book in SPORTSBOOKS:
            if book in g["books"]:
                label = BOOK_LABELS.get(book, book.upper())
                pct = g["books"][book]["nrfi_pct"]
                under = g["books"][book]["under"]
                book_parts.append(f"{label} {pct}% ({under:+d})")

        bpp_str = f"  BPP: {bpp['nrfi_pct']}%" if bpp and bpp.get("nrfi_pct") else ""
        books_str = "  " + " | ".join(book_parts) if book_parts else "  No odds"

        lines.append(f"**{g['away']} @ {g['home']}** — {time_str}\n{books_str}{bpp_str}")

    description = "\n\n".join(lines)
    embed = {
        "embeds": [{
            "title": f"🛡️ Today's NRFI Slate — {today_et()}",
            "description": description,
            "color": 0x3b82f6,
            "footer": {"text": "BPP sim + OddsBlaze (multi-book)"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    r = requests.post(DISCORD_WEBHOOK, json=embed, timeout=10)
    r.raise_for_status()
    print("  ✓ Morning summary sent")


# ── Degen Discord (webhook 2) ─────────────────────────────────────────────────
def _degen_color(nrfi_pct):
    if nrfi_pct is None: return 0x6b7280
    if nrfi_pct >= 55: return 0x22c55e
    if nrfi_pct >= 45: return 0xf59e0b
    return 0xef4444


def send_degen_game_alert(away, home, books, bpp_nrfi=None,
                          away_pitcher=None, home_pitcher=None):
    if not DISCORD_WEBHOOK_2:
        return

    color = _degen_color(bpp_nrfi)
    nrfi_str = f"**{bpp_nrfi}%**" if bpp_nrfi is not None else "—"

    odds_parts = []
    for book in SPORTSBOOKS:
        if book in books:
            label = BOOK_LABELS.get(book, book.upper())
            under = books[book]["under"]
            odds_parts.append(f"{label} {under:+d}")
    odds_str = " | ".join(odds_parts) if odds_parts else "No odds yet"

    starters = ""
    if away_pitcher or home_pitcher:
        starters = f"\n⚾ {away_pitcher or '?'} vs {home_pitcher or '?'}"

    embed = {
        "embeds": [{
            "title": f"🔒 {away} @ {home}",
            "description": f"NRFI: {nrfi_str}\n{odds_str}{starters}",
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    r = requests.post(DISCORD_WEBHOOK_2, json=embed, timeout=10)
    r.raise_for_status()


def send_degen_morning_summary(all_games: dict):
    if not DISCORD_WEBHOOK_2 or not all_games:
        return

    sorted_games = sorted(all_games.values(), key=lambda x: x["start"])
    lines = []

    for g in sorted_games:
        et_min = utc_to_et_minutes(g["start"])
        time_str = f"{et_min//60}:{et_min%60:02d}" if et_min else "TBD"

        odds_parts = []
        for book in SPORTSBOOKS:
            if book in g["books"]:
                label = BOOK_LABELS.get(book, book.upper())
                under = g["books"][book]["under"]
                odds_parts.append(f"{label} {under:+d}")
        odds_str = " | ".join(odds_parts) if odds_parts else "—"

        lines.append(f"**{g['away']} @ {g['home']}** — {time_str}\n{odds_str}")

    description = "\n\n".join(lines)
    embed = {
        "embeds": [{
            "title": f"🔒 NRFI Slate — {today_et()}",
            "description": description,
            "color": 0x3b82f6,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    r = requests.post(DISCORD_WEBHOOK_2, json=embed, timeout=10)
    r.raise_for_status()
    print("  ✓ Degen morning summary sent")


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

    print(f"\n[{datetime.now(timezone.utc).isoformat()}] NRFI Bot (multi-book)")
    print(f"  ET: {now_min//60}:{now_min%60:02d}  |  Morning mode: {is_morning}")

    # 1. Fetch all sportsbooks
    print("\n→ Fetching OddsBlaze (all books)...")
    try:
        all_games = fetch_all_books()
        print(f"  {len(all_games)} unique games across all books")
    except Exception as e:
        print(f"  OddsBlaze error: {e}")
        all_games = {}

    # Filter to only TODAY's games in ET
    all_games = {k: g for k, g in all_games.items() if utc_to_et_date(g["start"]) == today}
    print(f"  {len(all_games)} games on {today} ET")

    if not all_games:
        print("  No games today. Done.")
        return

    # 2. Scrape BallparkPal
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
            send_morning_summary(all_games, bpp_games)
            send_degen_morning_summary(all_games)
            mark_morning_summary_sent()
        return

    # ── Pre-game alerts (~1 hour before each game) ──
    win_lo = now_min + 50
    win_hi = now_min + 80
    print(f"\n→ Checking pre-game window: {win_lo//60}:{win_lo%60:02d}–{win_hi//60}:{win_hi%60:02d} ET")

    games_in_window = [
        g for g in all_games.values()
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
            books        = g["books"],
            bpp_nrfi     = bpp["nrfi_pct"] if bpp else None,
            away_win     = bpp["away_win_pct"] if bpp else None,
            home_win     = bpp["home_win_pct"] if bpp else None,
            away_pitcher = bpp["away_pitcher"] if bpp else None,
            home_pitcher = bpp["home_pitcher"] if bpp else None,
        )
        send_degen_game_alert(
            away         = g["away"],
            home         = g["home"],
            books        = g["books"],
            bpp_nrfi     = bpp["nrfi_pct"] if bpp else None,
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
