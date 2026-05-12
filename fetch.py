#!/usr/bin/env python3
"""
Fetches the current free seats from the Red Cross donor portal
and updates index.html with fresh data.

Usage:  python3 fetch.py
"""

import re
import sys
import json
from datetime import datetime
from html.parser import HTMLParser
from urllib.request import urlopen, Request
from urllib.error import URLError

URL = "https://donorportaal.rodekruis.be/collection?c=kBg5ngJJ1yu"
MAX_SEATS = 13

# All expected time slots — fully booked slots disappear from the page,
# so we fill them in as free=0 if they're missing from the response.
ALL_SLOTS = [
    "11:00", "11:15", "11:30", "11:45",
    "12:00", "12:15", "12:30", "12:45",
    "13:00", "13:15", "13:30", "13:45",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.8",
}


def fetch_html(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


class TableParser(HTMLParser):
    """Parses a table where the first column is a time (HH:MM)
    and a subsequent column contains a seat count (0–13)."""

    def __init__(self):
        super().__init__()
        self.slots: list[dict] = []
        self._in_tr = False
        self._in_td = False
        self._row: list[str] = []
        self._cell = ""

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._in_tr = True
            self._row = []
        elif tag in ("td", "th") and self._in_tr:
            self._in_td = True
            self._cell = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_td:
            self._in_td = False
            self._row.append(self._cell.strip())
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            self._process_row(self._row)

    def handle_data(self, data):
        if self._in_td:
            self._cell += data

    def _process_row(self, cells: list[str]):
        for i, cell in enumerate(cells):
            if re.match(r'^\d{1,2}:\d{2}$', cell):
                # Found a time cell — look for a number in the remaining cells
                for other in cells[i + 1:]:
                    clean = re.sub(r'\s+', '', other)
                    if re.match(r'^\d{1,2}$', clean):
                        free = int(clean)
                        if 0 <= free <= MAX_SEATS:
                            self.slots.append({
                                "time": cell,
                                "free": free,
                                "max": MAX_SEATS,
                            })
                            return
                break


def parse_via_booking_links(html: str) -> list[dict]:
    """
    Fallback: extract times from /Appointment/book?startTime=... links,
    then find the nearest standalone number before each link as the seat count.
    """
    pattern = re.compile(
        r'(\d{1,2})\s*(?:vrije?\s*plaatsen?|vrij|free|beschikbaar|available|seats?)?'
        r'(?:(?!startTime).){0,600}'
        r'startTime=(\d{4}-\d{2}-\d{2}[T%20+](\d{2})[%3A:](\d{2}))',
        re.S | re.I,
    )
    slots = []
    seen = set()
    for m in pattern.finditer(html):
        free = int(m.group(1))
        hour = m.group(3)
        minute = m.group(4)
        time_str = f"{hour}:{minute}"
        if time_str not in seen and 0 <= free <= MAX_SEATS:
            seen.add(time_str)
            slots.append({"time": time_str, "free": free, "max": MAX_SEATS})
    return slots


def parse_slots(html: str) -> list[dict]:
    # Strategy 1: proper table parser
    parser = TableParser()
    parser.feed(html)
    if parser.slots:
        return parser.slots

    # Strategy 2: booking link proximity
    slots = parse_via_booking_links(html)
    if slots:
        return slots

    # Strategy 3: embedded JSON
    json_match = re.search(r'"slots"\s*:\s*(\[.*?\])', html, re.S)
    if json_match:
        try:
            raw = json.loads(json_match.group(1))
            result = []
            for s in raw:
                time  = s.get("time") or s.get("startTime") or ""
                free  = s.get("freeSeats") or s.get("available") or 0
                result.append({"time": str(time)[:5], "free": int(free), "max": MAX_SEATS})
            if result:
                return result
        except Exception:
            pass

    return []


def fill_missing_slots(slots: list[dict]) -> list[dict]:
    """Add fully-booked slots (free=0) for any time that disappeared from the page."""
    found = {s["time"] for s in slots}
    full = [{"time": t, "free": 0, "max": MAX_SEATS} for t in ALL_SLOTS if t not in found]
    if full:
        print(f"  [info] {len(full)} slot(s) missing from page — assumed fully booked: "
              + ", ".join(s["time"] for s in full))
    combined = slots + full
    combined.sort(key=lambda s: s["time"])
    return combined


def update_html(slots: list[dict], timestamp: str) -> None:
    path = "index.html"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = ["  const SLOTS = ["]
    for s in slots:
        lines.append(f'    {{ time: "{s["time"]}", free: {s["free"]},  max: {s["max"]} }},')
    lines.append("  ];")
    new_block = "\n".join(lines)

    content = re.sub(r'  const SLOTS = \[.*?\];', new_block, content, flags=re.S)
    content = re.sub(
        r'const LAST_UPDATED = ".*?";',
        f'const LAST_UPDATED = "{timestamp}";',
        content,
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"index.html updated — {len(slots)} slots, timestamp {timestamp}")


def main():
    print(f"Fetching {URL} …")
    try:
        html = fetch_html(URL)
    except URLError as e:
        print(f"ERROR: could not reach the page — {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Downloaded {len(html)} bytes.")

    # Debug: print a snippet to help diagnose if parsing fails
    snippet_match = re.search(r'(?:11|12|13):\d{2}', html)
    if snippet_match:
        start = max(0, snippet_match.start() - 100)
        print(f"[debug] HTML snippet near first time: ...{html[start:start+300]}...")
    else:
        print("[debug] No HH:MM pattern found in HTML — page may require login.")
        print("[debug] First 500 chars:", html[:500])

    slots = parse_slots(html)
    if not slots:
        print("ERROR: no slots found. The portal may require authentication.", file=sys.stderr)
        sys.exit(1)

    slots = fill_missing_slots(slots)

    for s in slots:
        registered = s["max"] - s["free"]
        print(f"  {s['time']}  vrij={s['free']}  ingeschreven={registered}")

    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    update_html(slots, timestamp)
    print("Done. Refresh index.html in your browser to see updated data.")


if __name__ == "__main__":
    main()
