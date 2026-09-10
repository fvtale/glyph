"""Source registry.

Adapters are constructed from feed/feeds.json rather than hardcoded, so adding a
venue is a data change. Object key order in that file is the precedence order
used to break a dedupe tie between two scraped listings — explicit rather than
incidental.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Source, SourceError
from .ical import IcalSource

ROOT = Path(__file__).resolve().parents[2]
FEEDS = ROOT / "feed" / "feeds.json"
VENUES = ROOT / "public" / "data" / "venues.json"

ADAPTERS = {"ical": IcalSource}


def load_venues() -> dict[str, dict]:
    data = json.loads(VENUES.read_text(encoding="utf-8"))
    return {venue["id"]: venue for venue in data["venues"]}


def load_config() -> dict:
    return json.loads(FEEDS.read_text(encoding="utf-8"))


def build_sources(horizon_days: int = 240) -> list[Source]:
    """Every verified feed, in file order. Unverified entries are skipped."""
    config = load_config()
    venues = load_venues()
    sources: list[Source] = []
    for venue_id, entry in config.get("feeds", {}).items():
        if not entry.get("verified") or not entry.get("url"):
            continue
        venue = venues.get(venue_id)
        if venue is None:
            raise SourceError(f"feeds.json names unknown venue {venue_id!r}")
        adapter = ADAPTERS.get(entry.get("type", "ical"))
        if adapter is None:
            raise SourceError(f"{venue_id}: no adapter for type {entry.get('type')!r}")
        sources.append(adapter(venue, entry, horizon_days))
    return sources
