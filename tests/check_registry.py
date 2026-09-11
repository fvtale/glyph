#!/usr/bin/env python3
"""Check the hand-maintained data files against the contract.

The venue registry and feeds.json are edited by a person, which is exactly why
they need checking: a typo in a region name or a venue id would not raise an
exception, it would quietly cost a venue its listings. Run in CI on every push.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "feed"))

from build import (CURATED_DIR, KINDS, PROBE_TYPES, REGIONS,   # noqa: E402
                   as_curated, why_invalid)

VENUES = ROOT / "public" / "data" / "venues.json"
FEEDS = ROOT / "feed" / "feeds.json"
CURATED = ROOT / "feed" / "curated.json"
WRITERS = ROOT / "public" / "data" / "writers.json"

REQUIRED_VENUE_FIELDS = ("id", "name", "street", "neighborhood", "region", "site")


def main() -> int:
    problems: list[str] = []

    venues = json.loads(VENUES.read_text(encoding="utf-8"))["venues"]
    seen: set[str] = set()
    for venue in venues:
        label = venue.get("id") or venue.get("name") or "?"
        for field in REQUIRED_VENUE_FIELDS:
            if not venue.get(field):
                problems.append(f"venue {label}: missing {field}")
        if venue.get("id") in seen:
            problems.append(f"venue {label}: duplicate id")
        seen.add(venue.get("id"))
        if not re.fullmatch(r"[a-z0-9-]+", str(venue.get("id", ""))):
            problems.append(f"venue {label}: id is not kebab-case")
        if venue.get("region") not in REGIONS:
            problems.append(f"venue {label}: region {venue.get('region')!r} is not in the contract")
        if not str(venue.get("site", "")).startswith("https://"):
            problems.append(f"venue {label}: site is not https")

    feeds = json.loads(FEEDS.read_text(encoding="utf-8"))
    for venue_id, entry in feeds.get("feeds", {}).items():
        if venue_id not in seen:
            problems.append(f"feeds.json: {venue_id} is not in the venue registry")
        if entry.get("verified") and not entry.get("url"):
            problems.append(f"feeds.json: {venue_id} is marked verified with no url")
        fallback = entry.get("kindFallback", "reading")
        if fallback not in KINDS:
            problems.append(f"feeds.json: {venue_id} has kindFallback {fallback!r}")
    seen_conventions: set[str] = set()
    for convention in feeds.get("conventions", []):
        label = convention.get("id")
        if "{site}" not in convention.get("pattern", ""):
            problems.append(f"feeds.json: convention {label} has no {{site}}")
        if convention.get("type", "ical") not in PROBE_TYPES:
            problems.append(
                f"feeds.json: convention {label} has type "
                f"{convention.get('type')!r}, which the prober cannot judge"
            )
        if label in seen_conventions:
            problems.append(f"feeds.json: duplicate convention id {label}")
        seen_conventions.add(label)

    curated = json.loads(CURATED.read_text(encoding="utf-8"))
    for item in curated.get("events", []):
        if item.get("venueId") not in seen:
            problems.append(f"curated.json: {item.get('id')} names an unknown venue")
        if item.get("kind") not in KINDS:
            problems.append(f"curated.json: {item.get('id')} has kind {item.get('kind')!r}")

    # Approved listings, one per file. Checked for shape only: a merged reading
    # that has since happened is not broken, it is over, and the board drops it
    # by itself. Anything malformed, though, should never have been merged.
    venue_map = {venue["id"]: venue for venue in venues}
    approved = 0
    if CURATED_DIR.is_dir():
        for path in sorted(CURATED_DIR.glob("*.json")):
            approved += 1
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                problems.append(f"feed/curated/{path.name}: not valid JSON ({exc})")
                continue
            if not isinstance(item, dict):
                problems.append(f"feed/curated/{path.name}: not a JSON object")
                continue
            reason = why_invalid(as_curated(item), venue_map, temporal=False)
            if reason:
                problems.append(f"feed/curated/{path.name}: {reason}")
            if item.get("id") != path.stem:
                problems.append(f"feed/curated/{path.name}: file name does not match its id")

    # Nothing is publishable here without a recorded grant from the writer. A
    # missing grantedOn is a piece we cannot prove we were allowed to print.
    writers = json.loads(WRITERS.read_text(encoding="utf-8"))
    for writer in writers.get("writers", []):
        label = writer.get("slug") or writer.get("name") or "?"
        if not writer.get("slug") or not writer.get("name"):
            problems.append(f"writer {label}: needs both slug and name")
        for piece in writer.get("pieces", []):
            if not piece.get("text"):
                problems.append(f"writer {label}: a piece has no text")
            if not piece.get("grantedOn"):
                problems.append(
                    f"writer {label}: piece {piece.get('title')!r} has no grantedOn date"
                )

    if problems:
        print("Registry problems:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    wired = sum(1 for entry in feeds.get("feeds", {}).values() if entry.get("verified"))
    print(f"ok: {len(venues)} venues, {wired} verified feeds, "
          f"{len(curated.get('events', [])) + approved} curated listings, "
          f"{len(writers.get('writers', []))} writers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
