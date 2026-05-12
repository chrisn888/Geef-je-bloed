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
from urllib.request import urlopen, Request
from urllib.error import URLError

URL = "https://donorportaal.rodekruis.be/collection?c=kBg5ngJJ1yu"
MAX_SEATS = 13

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-BE,nl;q=0.9",
}


def fetch_html(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_slots(html: str) -> list[dict]:
    """
    Extract time slots and free-seat counts from the page HTML.
    The portal renders lines like:
        <span ...>11:00</span>  ...  <span ...>2 vrije plaatsen</span>
    or similar patterns — we look for HH:MM times next to seat numbers.
    """
    # Try to find JSON data embedded in the page (common in SPA portals)
    json_match = re.search(r'"slots"\s*:\s*(\[.*?\])', html, re.S)
    if json_match:
        try:
            raw = json.loads(json_match.group(1))
            slots = []
            for s in raw:
                time  = s.get("time") or s.get("startTime") or ""
                free  = s.get("freeSeats") or s.get("available") or 0
                slots.append({"time": str(time)[:5], "free": int(free), "max": MAX_SEATS})
            if slots:
                return slots
        except Exception:
            pass

    # Fallback: regex scan for "HH:MM" near a digit + seat keyword
    pattern = re.compile(
        r'(\d{1,2}:\d{2})'          # time like 11:00
        r'(?:(?!(?:\d{1,2}:\d{2})).){0,400}'   # up to 400 chars (no next time)
        r'(\d+)\s*(?:vrij|free|beschikbaar|available)',
        re.S | re.I,
    )
    slots = []
    for m in pattern.finditer(html):
        slots.append({
            "time": m.group(1),
            "free": int(m.group(2)),
            "max": MAX_SEATS,
        })
    return slots


def update_html(slots: list[dict], timestamp: str) -> None:
    path = "index.html"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Build new SLOTS array
    lines = ["  const SLOTS = ["]
    for s in slots:
        lines.append(f'    {{ time: "{s["time"]}", free: {s["free"]},  max: {s["max"]} }},')
    lines.append("  ];")
    new_slots_block = "\n".join(lines)

    # Replace existing SLOTS block
    content = re.sub(
        r'  const SLOTS = \[.*?\];',
        new_slots_block,
        content,
        flags=re.S,
    )
    # Replace timestamp
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

    slots = parse_slots(html)
    if not slots:
        print(
            "WARNING: no slots found in page. The portal may require a login "
            "or the HTML structure changed. Printing raw snippet for debugging:",
            file=sys.stderr,
        )
        print(html[:2000], file=sys.stderr)
        sys.exit(1)

    for s in slots:
        registered = s["max"] - s["free"]
        print(f"  {s['time']}  vrij={s['free']}  ingeschreven={registered}")

    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    update_html(slots, timestamp)
    print("Open index.html in your browser (or refresh) to see the updated data.")


if __name__ == "__main__":
    main()
