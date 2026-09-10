#!/usr/bin/env python3
"""Build public/data/events.json from the source adapters and curated.json.

Run in CI:     python feed/build.py
Dry run:       python feed/build.py --dry-run     (prints, writes nothing)
Probe feeds:   python feed/build.py --probe       (finds venue .ics endpoints)
First run:     python feed/build.py --bootstrap   (allowed to write an empty board)

Design rules this file enforces, in priority order:

1. Never blank the board. A run that produces zero listings writes nothing and
   fails loudly. A source that errors keeps its previous listings rather than
   dropping them.
2. Never clobber human input. feed/curated.json is merged on every run and
   always wins a dedupe tie.
3. Never commit noise. The output is compared ignoring every timestamp, so an
   unchanged board produces no commit and therefore no deploy.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sources import build_sources, load_config, load_venues   # noqa: E402
from sources.base import SourceError, normalize_title          # noqa: E402
from sources.http import polite_get                            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "public" / "data" / "events.json"
CURATED = ROOT / "feed" / "curated.json"

KINDS = {"reading", "openmic", "workshop", "launch", "panel"}
REGIONS = {
    "manhattan", "brooklyn", "queens", "bronx", "staten-island",
    "near-nj", "westchester", "long-island",
}
REQUIRED_FIELDS = (
    "id", "title", "kind", "date", "time", "venue", "venueId", "region",
    "url", "source",
)
MAX_HORIZON_DAYS = 240
MAX_EVENTS = 400


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def why_invalid(listing: dict, venues: dict[str, dict]) -> str | None:
    """Return the reason a listing cannot be published, or None if it can.

    Returning the reason rather than a bool is what makes a dry run useful: an
    adapter silently dropping half a venue's calendar is a bug worth seeing.
    """
    for field in REQUIRED_FIELDS:
        if not listing.get(field):
            return f"missing {field}"
    if listing["kind"] not in KINDS:
        return f"unknown kind {listing['kind']!r}"
    if listing["region"] not in REGIONS:
        return f"unknown region {listing['region']!r}"
    if listing["venueId"] not in venues:
        return f"venue {listing['venueId']!r} is not in the registry"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", listing["date"]):
        return f"bad date {listing['date']!r}"
    for field in ("time", "endTime"):
        value = listing.get(field)
        if value and not re.fullmatch(r"\d{2}:\d{2}", value):
            return f"bad {field} {value!r}"
    try:
        when = date.fromisoformat(listing["date"])
    except ValueError:
        return f"unparseable date {listing['date']!r}"
    today = date.today()
    if when < today:
        return "in the past"
    # A date years out is a parsing bug, not a listing.
    if when > today + timedelta(days=MAX_HORIZON_DAYS):
        return f"beyond the {MAX_HORIZON_DAYS}-day horizon"
    if not re.match(r"^https?://", listing["url"]):
        return f"url is not absolute http(s): {listing['url']!r}"
    if listing["kind"] != "workshop" and "registration" in listing:
        return "registration block on a non-workshop"
    return None


# ---------------------------------------------------------------------------
# reading what already exists
# ---------------------------------------------------------------------------

def read_previous() -> dict:
    if not OUTPUT.exists():
        return {"events": [], "coverage": {}}
    try:
        return json.loads(OUTPUT.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # Refusing to proceed is safer than overwriting a file we cannot read:
        # it may be the only copy of a board someone hand-fixed.
        sys.exit(f"error: {OUTPUT} is not valid JSON ({exc})")


def read_curated() -> list[dict]:
    if not CURATED.exists():
        return []
    data = json.loads(CURATED.read_text(encoding="utf-8"))
    listings = [dict(listing) for listing in data.get("events", [])]
    for listing in listings:
        listing["source"] = "curated"
    return listings


# ---------------------------------------------------------------------------
# the sweep
# ---------------------------------------------------------------------------

def sweep(sources) -> tuple[list[dict], dict[str, dict]]:
    """Fetch every source, isolating failures. Never raises."""
    fetched: list[dict] = []
    status: dict[str, dict] = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for source in sources:
        try:
            listings = source.fetch()
        except SourceError as exc:
            status[source.name] = {"ok": False, "count": 0, "error": str(exc)}
            print(f"  {source.name}: FAILED - {exc}", file=sys.stderr)
            continue
        except Exception as exc:              # an adapter bug is not fatal either
            status[source.name] = {"ok": False, "count": 0, "error": f"crash: {exc}"}
            print(f"  {source.name}: CRASHED - {exc}", file=sys.stderr)
            continue
        entry = {"ok": True, "count": len(listings), "fetchedAt": now}
        skipped = getattr(source, "skipped_all_day", 0)
        if skipped:
            entry["skippedAllDay"] = skipped
        status[source.name] = entry
        fetched.extend(listings)
        print(f"  {source.name}: {len(listings)} listings")
    return fetched, status


def merge(previous: dict, fetched: list[dict], status: dict[str, dict],
          curated: list[dict], live_sources: set[str]) -> list[dict]:
    """Rule 1 in code.

    A source that failed keeps whatever it contributed last time. A source that
    succeeded is fully replaced by what it just returned, so a cancelled reading
    actually disappears. A source no longer configured is dropped entirely -
    listings nobody maintains are worse than a shorter board.
    """
    failed = {name for name, entry in status.items() if not entry["ok"]}
    kept = [
        listing for listing in previous.get("events", [])
        if listing.get("source") in failed and listing.get("source") in live_sources
    ]
    if kept:
        print(f"  keeping {len(kept)} listings from {len(failed)} failed source(s)")
    return curated + fetched + kept


def dedupe(listings: list[dict], order: list[str]) -> list[dict]:
    """One listing per (date, venue, title). Curated wins, then source order."""
    rank = {name: index for index, name in enumerate(["curated"] + order)}
    fallback = len(rank)
    out: dict[tuple[str, str, str], dict] = {}
    for listing in listings:
        key = (listing["date"], listing["venueId"], normalize_title(listing["title"]))
        incumbent = out.get(key)
        if incumbent is None:
            out[key] = listing
            continue
        if rank.get(listing["source"], fallback) < rank.get(incumbent["source"], fallback):
            out[key] = listing
    return list(out.values())


def carry_first_seen(previous: dict, listings: list[dict]) -> None:
    """Preserve firstSeen across runs, so "new this week" means something."""
    known = {
        listing["id"]: listing["firstSeen"]
        for listing in previous.get("events", [])
        if listing.get("firstSeen")
    }
    today = date.today().isoformat()
    for listing in listings:
        listing["firstSeen"] = known.get(listing["id"], today)


# ---------------------------------------------------------------------------
# coverage - the honesty block
# ---------------------------------------------------------------------------

def build_coverage(venues: dict[str, dict], config: dict, status: dict[str, dict],
                   listings: list[dict]) -> dict:
    """Per region: venues registered, venues with a verified feed, listings live.

    Glyph claims the whole metro area. Claiming a region is not the same as
    covering one, so the gap gets published rather than left for a visitor to
    infer from an empty filter.
    """
    wired = {
        venue_id for venue_id, entry in config.get("feeds", {}).items()
        if entry.get("verified") and entry.get("url")
    }
    regions: dict[str, dict] = {
        region: {"venues": 0, "wired": 0, "listings": 0} for region in sorted(REGIONS)
    }
    for venue_id, venue in venues.items():
        bucket = regions[venue["region"]]
        bucket["venues"] += 1
        if venue_id in wired:
            bucket["wired"] += 1
    for listing in listings:
        regions[listing["region"]]["listings"] += 1
    return {"regions": regions, "sources": status}


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

def probe(venues: dict[str, dict], config: dict) -> int:
    """Try the convention patterns against every venue and report what answers.

    This exists because the development machine has neither Python nor a reason
    to be trusted about a venue's URL scheme. Feed URLs get verified here, from
    evidence, instead of by pasting a plausible-looking URL into feeds.json.
    """
    from icalendar import Calendar

    conventions = config.get("conventions", [])
    already = {
        venue_id for venue_id, entry in config.get("feeds", {}).items()
        if entry.get("verified")
    }
    found: dict[str, dict] = {}

    for venue_id, venue in venues.items():
        if venue_id in already:
            print(f"{venue_id}: already verified, skipping")
            continue
        site = (venue.get("site") or "").rstrip("/")
        if not site:
            print(f"{venue_id}: no site in the registry")
            continue
        print(f"{venue_id} ({site})")
        for convention in conventions:
            url = convention["pattern"].format(site=site)
            label = convention["id"]
            try:
                text = polite_get(url)
            except SourceError as exc:
                print(f"    {label:<16} - {exc}")
                continue
            if "BEGIN:VCALENDAR" not in text:
                print(f"    {label:<16} - 200 but not iCal")
                continue
            try:
                count = len(list(Calendar.from_ical(text).walk("VEVENT")))
            except Exception as exc:
                print(f"    {label:<16} - iCal that will not parse ({exc})")
                continue
            print(f"    {label:<16} - OK, {count} VEVENTs  {url}")
            if venue_id not in found:
                found[venue_id] = {
                    "type": "ical", "url": url, "verified": True,
                    "kindFallback": "reading",
                }

    print("\n" + "=" * 68)
    if not found:
        print("No feeds found. These venues need HTML adapters or curated entries.")
        return 0
    print("Verified feeds - paste into the feeds object in feed/feeds.json, after")
    print("checking that each URL really is that venue's public calendar:\n")
    print(json.dumps(found, indent=2))
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def fingerprint(payload: dict) -> str:
    """Everything that matters for a commit, and nothing that moves every run.

    Excludes generatedAt and every fetchedAt. Without this the board would
    commit twice a day forever, and every commit would trigger a deploy.
    """
    coverage = payload.get("coverage") or {}
    sources = {
        name: {"ok": entry.get("ok"), "count": entry.get("count")}
        for name, entry in (coverage.get("sources") or {}).items()
    }
    return json.dumps(
        {
            "events": payload.get("events", []),
            "regions": coverage.get("regions", {}),
            "sources": sources,
        },
        sort_keys=True,
    )


def emit_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and report, write nothing")
    parser.add_argument("--probe", action="store_true",
                        help="hunt for venue .ics endpoints and exit")
    parser.add_argument("--bootstrap", action="store_true",
                        help="permit writing an empty board (first run only)")
    args = parser.parse_args()

    venues = load_venues()
    config = load_config()

    if args.probe:
        return probe(venues, config)

    for venue_id, venue in venues.items():
        if venue.get("region") not in REGIONS:
            sys.exit(f"error: venue {venue_id!r} has no valid region")

    print("Sweeping sources:")
    sources = build_sources(MAX_HORIZON_DAYS)
    if not sources:
        print("  (no verified feeds yet - run with --probe, then fill in feeds.json)")
    fetched, status = sweep(sources)
    order = [source.name for source in sources]

    curated = read_curated()
    if curated:
        print(f"  curated: {len(curated)} listings")

    previous = read_previous()
    merged = merge(previous, fetched, status, curated, set(order))

    listings, dropped = [], []
    for listing in merged:
        reason = why_invalid(listing, venues)
        if reason:
            dropped.append((listing.get("id") or listing.get("title", "?"), reason))
        else:
            listings.append(listing)
    if dropped:
        print(f"\nDropped {len(dropped)}:")
        for what, reason in dropped[:25]:
            print(f"  {what}: {reason}")
        if len(dropped) > 25:
            print(f"  ... and {len(dropped) - 25} more")

    listings = dedupe(listings, order)
    listings.sort(key=lambda item: (item["date"], item["time"], item["venue"]))
    if len(listings) > MAX_EVENTS:
        print(f"\nCapping the board at {MAX_EVENTS} (had {len(listings)})")
        listings = listings[:MAX_EVENTS]
    carry_first_seen(previous, listings)

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample": False,
        "coverage": build_coverage(venues, config, status, listings),
        "events": listings,
    }

    print(f"\n{len(listings)} listings on the board")
    if not listings and not args.bootstrap:
        # Rule 1. An empty board is either a total outage or a bug, and either
        # way the right move is to leave yesterday's board up and shout.
        print("error: zero listings - refusing to blank the board", file=sys.stderr)
        emit_output("changed", "false")
        emit_output("count", "0")
        return 1

    changed = (not OUTPUT.exists()) or fingerprint(payload) != fingerprint(previous)
    emit_output("changed", "true" if changed else "false")
    emit_output("count", str(len(listings)))

    if args.dry_run:
        print("dry run - nothing written")
        return 0
    if not changed:
        print("unchanged - nothing written")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
