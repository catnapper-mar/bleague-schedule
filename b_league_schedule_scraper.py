
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B.League schedule scraper → Google Calendar CSV

Usage examples:
  # Alvark Tokyo, 2025-10 to 2026-05
  python b_league_schedule_scraper.py scrape --team alvark --start 2025-10 --end 2026-05 --out alvark_2025_10_to_2026_05.csv

  # Sunrockers Shibuya, 2025-10 to 2026-05
  python b_league_schedule_scraper.py scrape --team sunrockers --start 2025-10 --end 2026-05 --out sunrockers_2025_10_to_2026_05.csv

  # Validate a produced CSV against an expected one
  python b_league_schedule_scraper.py validate --actual your.csv --expected golden.csv
"""
import argparse
import csv
import dataclasses
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Tuple

try:
    import requests
    from bs4 import BeautifulSoup  # pip install beautifulsoup4
except Exception:
    requests = None
    BeautifulSoup = None

GOOGLE_HEADERS = [
    "Subject",
    "Start Date",
    "Start Time",
    "End Date",
    "End Time",
    "All Day Event",
    "Location",
]

TIMEDELTA_MINUTES = 150  # 2h30m

@dataclass
class Game:
    home_away: str  # "[HOME]" or "[AWAY]"
    opponent: str
    venue: str
    date: datetime
    start_time: Optional[str]  # "HH:MM" or None

    def to_row(self) -> List[str]:
        subject = f"{self.home_away} vs {self.opponent}@{self.venue}"
        if not self.start_time:
            subject += " ※時刻未定"
            return [
                subject,
                self.date.strftime("%Y-%m-%d"),
                "",
                self.date.strftime("%Y-%m-%d"),
                "",
                "True",   # Google Calendar expects True/False (capitalized)
                self.venue,
            ]
        # has start time
        start_dt = datetime.strptime(self.date.strftime("%Y-%m-%d") + " " + self.start_time, "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=TIMEDELTA_MINUTES)
        return [
            subject,
            self.date.strftime("%Y-%m-%d"),
            start_dt.strftime("%H:%M"),
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%H:%M"),
            "False",
            self.venue,
        ]

def month_iter(start: datetime, end: datetime) -> Iterable[Tuple[int, int]]:
    y, m = start.year, start.month
    while (y < end.year) or (y == end.year and m <= end.month):
        yield y, m
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1

# -------------------- Parsers --------------------

def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def parse_time(s: str) -> Optional[str]:
    """
    Extract "HH:MM" from strings like "19:05", "15:05", "18:05".
    If "未定" is found or no time, return None.
    """
    if "未定" in s:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    return f"{hh:02d}:{mm:02d}"


def _parse_schedule_list(year: int, month: int, soup, home_keywords: List[str]) -> List[Game]:
    games: List[Game] = []
    items = soup.select("div.tmpl_schedule_list ul.schedule-ul > li")
    for item in items:
        day_el = item.select_one("p.day")
        opp_el = item.select_one("td.team-name p")
        venue_el = item.select_one("p.stadium-name")
        if not (day_el and opp_el and venue_el):
            continue

        date_text = _clean_text(day_el.get_text(" ", strip=True))
        m = re.search(r"(\d{1,2})[./](\d{1,2})", date_text)
        if not m:
            continue
        mo = int(m.group(1))
        day = int(m.group(2))
        if mo != month:
            continue
        date = datetime(year, mo, day)

        venue = _clean_text(venue_el.get_text(" ", strip=True))
        opponent = _clean_text(opp_el.get_text(" ", strip=True))

        time_el = item.select_one("p.start-time")
        time_raw = _clean_text(time_el.get_text(" ", strip=True)) if time_el else ""
        start_time = parse_time(time_raw)

        home_el = item.select_one("p.a-h")
        home_tag = _clean_text(home_el.get_text(" ", strip=True)).upper() if home_el else ""
        home_away = "[HOME]" if "HOME" in home_tag else "[AWAY]"
        if not home_tag and any(keyword in venue for keyword in home_keywords):
            home_away = "[HOME]"

        games.append(Game(home_away, opponent, venue, date, start_time))

    keyed = {}
    for g in games:
        key = (g.date.strftime("%Y-%m-%d"), g.opponent, g.venue)
        keyed[key] = g
    return list(keyed.values())

def parse_alvark_month(year: int, month: int, html: str) -> List[Game]:
    """
    Parser for https://www.alvark-tokyo.jp/schedule/?scheduleYear=YYYY&scheduleMonth=M
    Robust strategy:
      - Find each game block (div/article li) containing date, opponent, venue, and time
      - Use regex-based fallbacks to avoid DOM-breaking changes
    """
    if BeautifulSoup is None:
        raise RuntimeError("BeautifulSoup is required. pip install beautifulsoup4")
    soup = BeautifulSoup(html, "html.parser")

    games = _parse_schedule_list(year, month, soup, home_keywords=["TOYOTA ARENA TOKYO"])
    if games:
        return games

    # heuristic: each game box has opponent and venue; search by common text markers
    cards = []
    # Try known container classes first; otherwise fall back to list items
    cards = soup.select(".p-schedule__item, .p-schedule-item, .schedule__item, li, article, div")
    games: List[Game] = []
    for el in cards:
        text = _clean_text(el.get_text(" "))
        if not text:
            continue
        # Must include either vs-like content or typical opponent markers
        if "vs" not in text and "アルバルク東京" not in text and "東京" not in text:
            continue

        # Date
        # examples: "2026.1.3", "1/3", "2025-11-01"
        date = None
        # Prefer explicit YYYY-M-D patterns on page title area; else build date from column header
        m1 = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
        m2 = re.search(r"(\d{1,2})[./](\d{1,2})", text)
        if m1:
            y, mo, d = map(int, m1.groups())
            date = datetime(y, mo, d)
        elif m2:
            mo, d = map(int, m2.groups())
            date = datetime(year, mo, d)
        else:
            # fallback: skip if no date inside this node
            continue

        # Opponent: parts after "vs" up to "@" or "@"-less fallback
        opponent = None
        op_m = re.search(r"vs\s*([^\s@|｜]+)", text, flags=re.IGNORECASE)
        if op_m:
            opponent = op_m.group(1)
        # A more robust approach: often opponent name appears before or after "vs"
        if not opponent:
            # attempt Japanese team name patterns (ひらがな/カタカナ/漢字/英字)
            # We cannot perfectly guarantee; fallback to trimming around "vs"
            parts = re.split(r"vs", text, flags=re.IGNORECASE)
            if len(parts) >= 2:
                tail = parts[1]
                opponent = _clean_text(re.split(r"[@＠]|会場|日時|時間", tail)[0])
                opponent = opponent.strip(" -|｜:：")
        if not opponent:
            continue  # skip ambiguous

        # Venue: after '@' or phrases like "会場:"
        venue = None
        at_m = re.search(r"[@＠]\s*([^\s].+?)(?:\s|$)", text)
        if at_m:
            venue = at_m.group(1).strip(" 、，,)|）)]")
        if not venue:
            v_m = re.search(r"(会場[:：]\s*)(.+?)(?:\s|$)", text)
            if v_m:
                venue = v_m.group(2).strip(" 、，,)|）)]")
        if not venue:
            # last resort: look for known arenas
            known_arenas = ["TOYOTA ARENA TOKYO", "おおきにアリーナ舞洲", "CNAアリーナ", "ゼビオアリーナ", "IGアリーナ"]
            for a in known_arenas:
                if a in text:
                    venue = a
                    break
        if not venue:
            continue

        # Time
        start_time = parse_time(text)

        # Home/Away: page often describes it; fallback by venue containing home arena
        home_away = "[AWAY]"
        if any(x in venue for x in ["TOYOTA ARENA TOKYO"]):
            home_away = "[HOME]"
        # Some pages mark HOME/AWAY textually
        if "HOME" in text.upper():
            home_away = "[HOME]"
        if "AWAY" in text.upper():
            home_away = "[AWAY]"

        games.append(Game(home_away, opponent, venue, date, start_time))

    # Deduplicate by (date, opponent, venue)
    keyed = {}
    for g in games:
        key = (g.date.strftime("%Y-%m-%d"), g.opponent, g.venue)
        keyed[key] = g
    return list(keyed.values())

def parse_sunrockers_month(year: int, month: int, html: str) -> List[Game]:
    """
    Parser for https://www.sunrockers.jp/schedule/?scheduleYear=YYYY&scheduleMonth=M
    Strategy mirrors Alvark parser with adjusted home venue hints.
    """
    if BeautifulSoup is None:
        raise RuntimeError("BeautifulSoup is required. pip install beautifulsoup4")
    soup = BeautifulSoup(html, "html.parser")
    games = _parse_schedule_list(
        year,
        month,
        soup,
        home_keywords=["青山学院記念館", "ひがしんアリーナ"],
    )
    if games:
        return games
    candidates = soup.select(".p-schedule__item, .schedule__item, li, article, div")
    games: List[Game] = []
    for el in candidates:
        text = _clean_text(el.get_text(" "))
        if not text:
            continue
        if "vs" not in text and "サンロッカーズ" not in text:
            continue

        # Date
        date = None
        m1 = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
        m2 = re.search(r"(\d{1,2})[./](\d{1,2})", text)
        if m1:
            y, mo, d = map(int, m1.groups())
            date = datetime(y, mo, d)
        elif m2:
            mo, d = map(int, m2.groups())
            date = datetime(year, mo, d)
        else:
            continue

        # Opponent
        opponent = None
        op_m = re.search(r"vs\s*([^\s@|｜]+)", text, flags=re.IGNORECASE)
        if op_m:
            opponent = op_m.group(1)
        if not opponent:
            parts = re.split(r"vs", text, flags=re.IGNORECASE)
            if len(parts) >= 2:
                tail = parts[1]
                opponent = _clean_text(re.split(r"[@＠]|会場|日時|時間", tail)[0])
                opponent = opponent.strip(" -|｜:：")
        if not opponent:
            continue

        # Venue
        venue = None
        at_m = re.search(r"[@＠]\s*([^\s].+?)(?:\s|$)", text)
        if at_m:
            venue = at_m.group(1).strip(" 、，,)|）)]")
        if not venue:
            v_m = re.search(r"(会場[:：]\s*)(.+?)(?:\s|$)", text)
            if v_m:
                venue = v_m.group(2).strip(" 、，,)|）)]")
        if not venue:
            known_arenas = ["青山学院記念館", "ひがしんアリーナ", "国立代々木競技場 第二体育館", "横浜BUNTAI", "IGアリーナ"]
            for a in known_arenas:
                if a in text:
                    venue = a
                    break
        if not venue:
            continue

        # Time
        start_time = parse_time(text)

        # Home/Away (home arenas contain 青山学院記念館 / ひがしんアリーナ)
        home_away = "[AWAY]"
        if any(x in venue for x in ["青山学院記念館", "ひがしんアリーナ"]):
            home_away = "[HOME]"
        if "HOME" in text.upper():
            home_away = "[HOME]"
        if "AWAY" in text.upper():
            home_away = "[AWAY]"

        games.append(Game(home_away, opponent, venue, date, start_time))

    keyed = {}
    for g in games:
        key = (g.date.strftime("%Y-%m-%d"), g.opponent, g.venue)
        keyed[key] = g
    return list(keyed.values())

def fetch_month(team: str, y: int, m: int) -> str:
    if requests is None:
        raise RuntimeError("requests is required. pip install requests")
    if team == "alvark":
        url = f"https://www.alvark-tokyo.jp/schedule/?scheduleYear={y}&scheduleMonth={m}"
    elif team == "sunrockers":
        url = f"https://www.sunrockers.jp/schedule/?scheduleYear={y}&scheduleMonth={m}"
    else:
        raise ValueError("Unknown team")
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return resp.text

def scrape(team: str, start_ym: str, end_ym: str) -> List[Game]:
    start = datetime.strptime(start_ym, "%Y-%m")
    end = datetime.strptime(end_ym, "%Y-%m")
    all_games: List[Game] = []
    for y, m in month_iter(start, end):
        html = fetch_month(team, y, m)
        if team == "alvark":
            games = parse_alvark_month(y, m, html)
        else:
            games = parse_sunrockers_month(y, m, html)
        all_games.extend(games)
    # Sort
    all_games.sort(key=lambda g: (g.date, g.start_time or "23:59", g.venue))
    return all_games

def write_google_csv(games: List[Game], out_path: str) -> None:
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(GOOGLE_HEADERS)
        for g in games:
            writer.writerow(g.to_row())

# -------------------- Validation --------------------

def read_csv(path: str) -> List[List[str]]:
    rows: List[List[str]] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader, [])
        # Normalize headers order (must match GOOGLE_HEADERS)
        if [h.strip() for h in headers] != GOOGLE_HEADERS:
            raise ValueError(f"Unexpected headers in {path}: {headers}")
        for r in reader:
            rows.append([c.strip() for c in r])
    return rows

def validate_csv(actual_path: str, expected_path: str) -> Tuple[bool, List[str]]:
    act = read_csv(actual_path)
    exp = read_csv(expected_path)
    ok = (act == exp)
    diffs: List[str] = []
    if not ok:
        # Simple diff: show first 10 differences
        n = min(len(act), len(exp))
        for i in range(n):
            if act[i] != exp[i]:
                diffs.append(f"Row {i+2} differs:\n  actual:   {act[i]}\n  expected: {exp[i]}")
                if len(diffs) >= 10:
                    break
        if len(act) != len(exp):
            diffs.append(f"Length differs: actual={len(act)} expected={len(exp)}")
    return ok, diffs

# -------------------- CLI --------------------

def main():
    p = argparse.ArgumentParser(description="B.League schedule → Google Calendar CSV")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_scrape = sub.add_parser("scrape", help="Scrape website and export CSV")
    p_scrape.add_argument("--team", choices=["alvark", "sunrockers"], required=True)
    p_scrape.add_argument("--start", required=True, help="YYYY-MM")
    p_scrape.add_argument("--end", required=True, help="YYYY-MM")
    p_scrape.add_argument("--out", required=True, help="Output CSV path")

    p_val = sub.add_parser("validate", help="Compare actual CSV with expected CSV")
    p_val.add_argument("--actual", required=True)
    p_val.add_argument("--expected", required=True)

    args = p.parse_args()

    if args.cmd == "scrape":
        games = scrape(args.team, args.start, args.end)
        write_google_csv(games, args.out)
        print(f"Wrote {len(games)} rows to {args.out}")
    elif args.cmd == "validate":
        ok, diffs = validate_csv(args.actual, args.expected)
        if ok:
            print("✅ CSVs match exactly.")
        else:
            print("❌ CSVs differ.")
            for d in diffs:
                print(d)

if __name__ == "__main__":
    main()
