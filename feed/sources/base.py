"""The contract every source adapter implements.

A source knows how to reach one provider and return listings already shaped to
the contract in docs/feed-contract.md. It never writes files, never merges, and
never decides what lands on the board — build.py owns all of that. Keeping
adapters this thin is what lets a venue be added, replaced or dropped without
touching anything else.
"""

from __future__ import annotations

import re
import unicodedata

# Every timestamp a venue publishes is local to New York unless it says
# otherwise, and the board is a New York board, so all times normalize here.
NYC_TZ = "America/New_York"


class SourceError(Exception):
    """Raised when a source cannot produce data. build.py isolates these so one
    failing venue never takes down the run, and so a venue that breaks keeps its
    previous listings instead of vanishing from the board."""


class Source:
    #: Stable identifier stamped onto every listing this adapter produces. Used
    #: to decide which existing listings a successful run may replace.
    name: str = "unnamed"

    #: Venue this adapter speaks for, joined against public/data/venues.json.
    venue_id: str = ""

    def fetch(self) -> list[dict]:
        """Return listings in contract shape. Raise SourceError on failure."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------

def clean_text(value: str | None, limit: int = 240) -> str:
    """Collapse whitespace and trim to the contract's description budget."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"<[^>]+>", " ", text)          # venue feeds often carry HTML
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    # Cut at a word boundary rather than mid-word.
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",.;:—-") + "…"


def slugify(value: str, limit: int = 48) -> str:
    """ASCII slug used to build stable listing ids."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:limit].rstrip("-") or "untitled"


def normalize_title(value: str) -> str:
    """Dedupe key component: case-folded, accent-stripped, punctuation-collapsed.

    Two venues describing the same night rarely agree on punctuation or on
    whether the reader's middle initial is in the title.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def make_id(venue_id: str, date: str, title: str) -> str:
    """Stable across runs, which is what lets firstSeen survive."""
    return f"{venue_id}-{date}-{slugify(title, 40)}"


# ---------------------------------------------------------------------------
# kind inference
# ---------------------------------------------------------------------------

# Ordered most-specific first: a "book launch reading" is a launch, and a
# "generative workshop" is a workshop even though the word "reading" appears in
# the description. A venue can override the fallback in feed/feeds.json.
KIND_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("workshop", ("workshop", "generative", "craft class", "masterclass",
                  "seminar", "course", "manuscript", "intensive", "class with",
                  "writing class")),
    ("openmic",  ("open mic", "open-mic", "openmic", "slam", "sign-up",
                  "sign up", "mic night", "cypher")),
    ("launch",   ("launch", "signing", "release party", "book party",
                  "publication party", "on tour")),
    ("panel",    ("panel", "craft talk", "in conversation", "conversation with",
                  "discussion", "symposium", "lecture", "interview",
                  "storytelling", "roundtable", "q&a")),
)


def infer_kind(title: str, description: str = "", fallback: str = "reading") -> str:
    """Guess a listing's kind from its own words.

    Guessing is acceptable here in a way it is not for accessibility or price:
    a mis-filed listing is still findable and still links out correctly, whereas
    a wrong step-free claim sends someone to a staircase.
    """
    haystack = f"{title} {description}".casefold()
    for kind, needles in KIND_PATTERNS:
        if any(needle in haystack for needle in needles):
            return kind
    return fallback
