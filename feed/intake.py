#!/usr/bin/env python3
"""Judge a listings/* branch and write the pull request that proposes it.

The email receptionist in datarail-agents reads a venue's email, drafts the
listings, and pushes them here as a branch named listings/<ref> with one file
per listing under feed/curated/. This script is what decides whether they are
any good — using the same why_invalid() the board builder uses, so there is
exactly one definition of a publishable listing, and the agent that drafted a
proposal never gets to be the judge of it.

    python feed/intake.py --base origin/main --body pr_body.md

It always exits 0 and puts the verdict in the pull request instead. A proposal
with problems still becomes a PR, as a draft with the problems at the top: a
malformed submission is something a person should see, not something that
quietly never arrives.

This repository is public, so everything written into the pull request comes
from the listing files — which hold only what the venue wants published — and
never from the email itself. No sender address, no name, no subject, no body.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build import CURATED, CURATED_DIR, ROOT, emit_output, why_invalid   # noqa: E402
from sources import load_venues                                        # noqa: E402
from sources.base import normalize_title                               # noqa: E402

# Where a listing's link may reasonably point besides the venue's own site.
# A link anywhere else is not blocked — venues use all sorts of partners — but
# it is flagged, because a changed link is the cheapest way to turn a calendar
# into a phishing page.
TICKETING_HOSTS = (
    "eventbrite.com", "dice.fm", "ovationtix.com", "ticketweb.com",
    "ticketmaster.com", "seetickets.us", "tix.com", "universe.com",
    "withfriends.co", "lu.ma", "partiful.com", "showclix.com", "simpletix.com",
    "ticketleap.com", "squadup.com", "zeffy.com", "givebutter.com",
    "brownpapertickets.com", "humanitix.com", "tickettailor.com",
)

TITLE_LIMIT = 120


@dataclass
class Verdict:
    name: str                       # file name, for the reviewer to find it
    listing: dict | None
    problems: list[str] = field(default_factory=list)   # block a one-click merge
    warnings: list[str] = field(default_factory=list)   # worth a look, not a block


# ---------------------------------------------------------------------------
# judgement — pure, so it is tested without git or a network
# ---------------------------------------------------------------------------

def host_of(url: str) -> str:
    host = (urlsplit(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def link_warning(url: str, venue: dict | None) -> str | None:
    """Flag a link that goes somewhere other than the venue or a ticket seller."""
    host = host_of(url)
    if not host:
        return None
    site = host_of((venue or {}).get("site", ""))
    if site and (host == site or host.endswith("." + site)):
        return None
    if any(host == known or host.endswith("." + known) for known in TICKETING_HOSTS):
        return None
    return f"links to {host}, which is neither the venue's site nor a known ticket seller"


def review(proposed: list[tuple[str, object]], venues: dict[str, dict],
           existing: list[dict]) -> list[Verdict]:
    """Judge each proposed file. `proposed` is (file name, parsed JSON or None)."""
    known_ids = {item.get("id") for item in existing}
    known_keys = {
        (item.get("date"), item.get("venueId"), normalize_title(item.get("title", ""))): item.get("id")
        for item in existing
    }

    verdicts: list[Verdict] = []
    for name, data in proposed:
        if not isinstance(data, dict):
            verdicts.append(Verdict(name, None, ["not a JSON object"]))
            continue
        verdict = Verdict(name, data)

        # The full check, dates included: a new proposal for last Tuesday is a
        # typo in the year, not a reading that already happened.
        reason = why_invalid(data, venues, temporal=True)
        if reason:
            verdict.problems.append(reason)

        if data.get("id") and Path(name).stem != data["id"]:
            verdict.problems.append(f"file name does not match id {data['id']!r}")
        if data.get("id") in known_ids:
            verdict.problems.append("that id is already on the board")
        else:
            key = (data.get("date"), data.get("venueId"),
                   normalize_title(data.get("title", "")))
            if key in known_keys:
                verdict.problems.append(f"looks like a duplicate of {known_keys[key]}")

        warning = link_warning(data.get("url", ""), venues.get(data.get("venueId", "")))
        if warning:
            verdict.warnings.append(warning)
        if not data.get("price"):
            verdict.warnings.append("no price given — check whether it is free")

        verdicts.append(verdict)
    return verdicts


def is_clean(verdicts: list[Verdict]) -> bool:
    return bool(verdicts) and not any(verdict.problems for verdict in verdicts)


def when_text(listing: dict) -> str:
    try:
        day = date.fromisoformat(listing.get("date", ""))
        stamp = day.strftime("%a %d %b %Y").replace(" 0", " ")
    except ValueError:
        stamp = listing.get("date") or "?"
    clock = listing.get("time") or ""
    if re.fullmatch(r"\d{2}:\d{2}", clock):
        hour, minute = int(clock[:2]), clock[3:]
        suffix = "AM" if hour < 12 else "PM"
        hour = hour % 12 or 12
        clock = f"{hour} {suffix}" if minute == "00" else f"{hour}:{minute} {suffix}"
    return f"{stamp}, {clock}" if clock else stamp


def cell(value) -> str:
    """Table-safe text: a pipe or newline in a title would break the row."""
    return re.sub(r"[|\r\n]+", " ", str(value or "")).strip() or "—"


def compose_body(verdicts: list[Verdict], notes: str) -> str:
    lines: list[str] = []
    if not verdicts:
        lines += ["## Nothing to propose", "",
                  "This branch adds no listing files under `feed/curated/`.", ""]
    else:
        clean = is_clean(verdicts)
        lines += [
            "## " + ("Ready to merge" if clean else "Needs attention before merging"),
            "",
            "| | Listing | When | Venue | Kind | Price |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for verdict in verdicts:
            item = verdict.listing or {}
            mark = "❌" if verdict.problems else ("⚠️" if verdict.warnings else "✅")
            title = cell(item.get("title") or verdict.name)
            url = item.get("url", "")
            linked = f"[{title}]({url})" if re.match(r"^https?://", url or "") else title
            lines.append(
                f"| {mark} | {linked} | {cell(when_text(item))} | {cell(item.get('venue'))} "
                f"| {cell(item.get('kind'))} | {cell(item.get('price'))} |"
            )
        lines.append("")

        flagged = [verdict for verdict in verdicts if verdict.problems or verdict.warnings]
        if flagged:
            lines += ["### What the checks found", ""]
            for verdict in flagged:
                for problem in verdict.problems:
                    lines.append(f"- ❌ `{verdict.name}` — {problem}")
                for warning in verdict.warnings:
                    lines.append(f"- ⚠️ `{verdict.name}` — {warning}")
            lines.append("")

    lines += [
        "### Before merging",
        "",
        "- [ ] Open each link and check the date, time and price against the venue's own page",
        "- [ ] Compare with the original email, filed in `Agent/Listings`",
        "",
    ]
    if notes.strip():
        lines += ["### From the receptionist", "", notes.strip(), ""]
    lines += [
        "---",
        "<sub>Checked against docs/feed-contract.md by feed/intake.py. "
        "Merging publishes on the next board build.</sub>",
    ]
    return "\n".join(lines) + "\n"


def pr_title(subject: str, verdicts: list[Verdict]) -> str:
    """One line, bounded. It reaches GITHUB_OUTPUT, where a newline would let
    submitted text write outputs of its own."""
    text = re.sub(r"\s+", " ", subject or "").strip()
    if not text:
        count = sum(1 for verdict in verdicts if verdict.listing)
        text = f"Listing proposal ({count} listing{'s' if count != 1 else ''})"
    if len(text) > TITLE_LIMIT:
        text = text[: TITLE_LIMIT - 1].rstrip() + "…"
    return text


# ---------------------------------------------------------------------------
# the branch
# ---------------------------------------------------------------------------

def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


def added_files(base: str) -> list[Path]:
    output = git("diff", "--name-only", "--diff-filter=A", f"{base}...HEAD",
                 "--", str(CURATED_DIR.relative_to(ROOT)))
    return [ROOT / line for line in output.splitlines()
            if line.strip().endswith(".json")]


def parse(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def existing_listings(exclude: set[Path]) -> list[dict]:
    listings: list[dict] = []
    if CURATED.exists():
        listings.extend(json.loads(CURATED.read_text(encoding="utf-8")).get("events", []))
    if CURATED_DIR.is_dir():
        for path in sorted(CURATED_DIR.glob("*.json")):
            if path in exclude:
                continue
            data = parse(path)
            if isinstance(data, dict):
                listings.append(data)
    return listings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main",
                        help="what the proposal is compared against")
    parser.add_argument("--body", required=True,
                        help="where to write the pull request body")
    args = parser.parse_args()

    files = added_files(args.base)
    proposed = [(path.name, parse(path)) for path in files]
    verdicts = review(proposed, load_venues(), existing_listings(set(files)))

    notes = git("log", "-1", "--format=%b")
    body = compose_body(verdicts, notes)
    Path(args.body).write_text(body, encoding="utf-8")

    clean = is_clean(verdicts)
    emit_output("clean", "true" if clean else "false")
    emit_output("title", pr_title(git("log", "-1", "--format=%s"), verdicts))
    print(body)
    print("clean" if clean else "needs attention — will open as a draft")
    return 0


if __name__ == "__main__":
    sys.exit(main())
