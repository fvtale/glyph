"""Tests for the listings builder.

There is no Python on the development machine, so this file is the only thing
that ever runs feed/build.py before it runs for real. It leans on the parts that
would fail silently and wrongly rather than loudly: validation, the never-blank
merge, dedupe precedence, and the fingerprint that decides whether to commit.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "feed"))

import build                                     # noqa: E402
from sources.base import infer_kind, make_id, normalize_title   # noqa: E402

VENUES = {"kgb-bar": {"id": "kgb-bar", "name": "KGB Bar", "region": "manhattan"}}


def listing(**overrides) -> dict:
    base = {
        "id": "kgb-bar-2099-01-01-prose-night",
        "title": "Prose night",
        "kind": "reading",
        "date": (date.today() + timedelta(days=7)).isoformat(),
        "time": "19:00",
        "venue": "KGB Bar",
        "venueId": "kgb-bar",
        "region": "manhattan",
        "url": "https://www.kgbbar.com",
        "source": "kgb-bar",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def test_a_complete_listing_is_publishable():
    assert build.why_invalid(listing(), VENUES) is None


@pytest.mark.parametrize("field", build.REQUIRED_FIELDS)
def test_every_required_field_is_required(field):
    item = listing()
    del item[field]
    assert build.why_invalid(item, VENUES) == f"missing {field}"


def test_yesterday_is_not_a_listing():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert build.why_invalid(listing(date=yesterday), VENUES) == "in the past"


def test_today_still_counts():
    # A reading tonight is the single most useful row on the board.
    assert build.why_invalid(listing(date=date.today().isoformat()), VENUES) is None


def test_a_date_past_the_horizon_is_a_parsing_bug():
    far = (date.today() + timedelta(days=build.MAX_HORIZON_DAYS + 1)).isoformat()
    assert "horizon" in build.why_invalid(listing(date=far), VENUES)


@pytest.mark.parametrize("bad", ["7pm", "19:00:00", "1900", ""])
def test_time_must_be_hh_mm(bad):
    reason = build.why_invalid(listing(time=bad), VENUES)
    assert reason is not None


def test_unknown_venue_is_dropped():
    reason = build.why_invalid(listing(venueId="not-a-venue"), VENUES)
    assert "registry" in reason


def test_unknown_kind_and_region_are_dropped():
    assert "kind" in build.why_invalid(listing(kind="concert"), VENUES)
    assert "region" in build.why_invalid(listing(region="philadelphia"), VENUES)


def test_relative_url_is_dropped():
    # A listing nobody can click through to is not publishable: the venue page
    # is the authority, and without it the row is an unverifiable claim.
    assert "absolute" in build.why_invalid(listing(url="/events/1"), VENUES)


def test_shape_only_check_accepts_a_listing_that_is_simply_over():
    # A merged reading from last week is not a broken file; CI must not go red
    # every morning as approved listings age out.
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert build.why_invalid(listing(date=yesterday), VENUES, temporal=False) is None


def test_shape_only_check_still_rejects_an_impossible_date():
    assert build.why_invalid(listing(date="2026-13-45"), VENUES, temporal=False)


def test_curated_reads_the_file_and_one_listing_per_file(tmp_path, monkeypatch):
    curated_file = tmp_path / "curated.json"
    curated_file.write_text('{"events": [{"id": "from-the-file"}]}', encoding="utf-8")
    folder = tmp_path / "curated"
    folder.mkdir()
    (folder / "from-a-file.json").write_text('{"id": "from-a-file"}', encoding="utf-8")
    (folder / "broken.json").write_text("{not json", encoding="utf-8")
    (folder / "README.md").write_text("not a listing", encoding="utf-8")
    monkeypatch.setattr(build, "CURATED", curated_file)
    monkeypatch.setattr(build, "CURATED_DIR", folder)

    listings = build.read_curated()
    # One malformed file is skipped rather than taking the board down.
    assert sorted(item["id"] for item in listings) == ["from-a-file", "from-the-file"]
    assert all(item["source"] == "curated" for item in listings)


def test_registration_belongs_only_to_workshops():
    item = listing(registration={"deadline": "2099-01-01"})
    assert build.why_invalid(item, VENUES) == "registration block on a non-workshop"
    workshop = listing(kind="workshop", registration={"deadline": "2099-01-01"})
    assert build.why_invalid(workshop, VENUES) is None


# ---------------------------------------------------------------------------
# rule 1: never blank the board
# ---------------------------------------------------------------------------

def test_a_failed_source_keeps_its_previous_listings():
    previous = {"events": [listing(id="old", source="kgb-bar")]}
    status = {"kgb-bar": {"ok": False, "count": 0, "error": "HTTP 503"}}
    merged = build.merge(previous, [], status, [], {"kgb-bar"})
    assert [item["id"] for item in merged] == ["old"]


def test_a_successful_source_replaces_its_previous_listings():
    previous = {"events": [listing(id="old", source="kgb-bar")]}
    status = {"kgb-bar": {"ok": True, "count": 1}}
    fresh = [listing(id="new", source="kgb-bar")]
    merged = build.merge(previous, fresh, status, [], {"kgb-bar"})
    # A cancelled reading has to be able to disappear.
    assert [item["id"] for item in merged] == ["new"]


def test_a_source_no_longer_configured_is_dropped_entirely():
    previous = {"events": [listing(id="old", source="retired-venue")]}
    status = {"kgb-bar": {"ok": False, "count": 0, "error": "boom"}}
    merged = build.merge(previous, [], status, [], {"kgb-bar"})
    assert merged == []


# ---------------------------------------------------------------------------
# rule 2: never clobber human input
# ---------------------------------------------------------------------------

def test_curated_wins_a_dedupe_tie():
    scraped = listing(id="scraped", title="Prose Night!", source="kgb-bar")
    curated = listing(id="curated", title="prose night", source="curated")
    out = build.dedupe([scraped, curated], ["kgb-bar"])
    assert len(out) == 1
    assert out[0]["id"] == "curated"


def test_source_order_breaks_a_tie_between_two_scrapers():
    first = listing(id="first", source="alpha")
    second = listing(id="second", source="beta")
    out = build.dedupe([second, first], ["alpha", "beta"])
    assert out[0]["id"] == "first"


def test_different_days_at_one_venue_are_not_duplicates():
    day_one = listing(id="a", date=(date.today() + timedelta(days=1)).isoformat())
    day_two = listing(id="b", date=(date.today() + timedelta(days=2)).isoformat())
    assert len(build.dedupe([day_one, day_two], ["kgb-bar"])) == 2


# ---------------------------------------------------------------------------
# rule 3: never commit noise
# ---------------------------------------------------------------------------

def payload(events, generated="2026-01-01T00:00:00+00:00", fetched="x"):
    return {
        "generatedAt": generated,
        "sample": False,
        "coverage": {
            "regions": {"manhattan": {"venues": 1, "wired": 1, "listings": len(events)}},
            "sources": {"kgb-bar": {"ok": True, "count": len(events), "fetchedAt": fetched}},
        },
        "events": events,
    }


def test_timestamps_alone_are_not_a_change():
    events = [listing()]
    before = payload(events, generated="2026-01-01T00:00:00+00:00", fetched="then")
    after = payload(events, generated="2026-06-06T12:00:00+00:00", fetched="now")
    assert build.fingerprint(before) == build.fingerprint(after)


def test_a_new_listing_is_a_change():
    assert build.fingerprint(payload([listing()])) != build.fingerprint(payload([]))


def test_a_source_going_down_is_a_change():
    before = payload([listing()])
    after = payload([listing()])
    after["coverage"]["sources"]["kgb-bar"]["ok"] = False
    assert build.fingerprint(before) != build.fingerprint(after)


def test_fingerprint_survives_a_file_with_no_coverage_block():
    # An events.json written before coverage existed must not crash the build.
    assert build.fingerprint({"events": []})


# ---------------------------------------------------------------------------
# firstSeen
# ---------------------------------------------------------------------------

def test_first_seen_is_carried_across_runs():
    previous = {"events": [dict(listing(), firstSeen="2026-01-01")]}
    current = [listing()]
    build.carry_first_seen(previous, current)
    assert current[0]["firstSeen"] == "2026-01-01"


def test_a_listing_never_seen_before_is_first_seen_today():
    current = [listing(id="brand-new")]
    build.carry_first_seen({"events": []}, current)
    assert current[0]["firstSeen"] == date.today().isoformat()


# ---------------------------------------------------------------------------
# adapter helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Generative workshop: four Tuesdays", "workshop"),
    ("Open mic, sign-up at 6:30", "openmic"),
    ("Friday night slam", "openmic"),
    ("Debut collection launch", "launch"),
    ("Signing and short reading", "launch"),
    ("Craft talk: revision as demolition", "panel"),
    ("In conversation with the translator", "panel"),
    ("Two poets, thirty minutes each", "reading"),
    ("", "reading"),
])
def test_kind_inference(title, expected):
    assert infer_kind(title) == expected


def test_a_workshop_that_mentions_reading_is_still_a_workshop():
    assert infer_kind("Workshop", "We will be reading each other's drafts") == "workshop"


def test_the_venue_fallback_applies_when_nothing_matches():
    assert infer_kind("Thursday night", fallback="openmic") == "openmic"


def test_titles_normalize_across_punctuation_and_accents():
    assert normalize_title("Café Reading!") == normalize_title("cafe   reading")


# ---------------------------------------------------------------------------
# probe response judgement — the call that decides whether a venue gets wired
# ---------------------------------------------------------------------------

ICAL = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
    "BEGIN:VEVENT\r\nUID:1\r\nDTSTART:20990101T190000Z\r\nSUMMARY:A reading\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n"
)


def test_real_ical_is_accepted():
    ok, description = build.describe_probe_response("ical", ICAL)
    assert ok and "1 VEVENTs" in description


def test_an_html_page_is_not_a_calendar():
    ok, description = build.describe_probe_response("ical", "<html>events</html>")
    assert not ok and description == "200 but not iCal"


def test_an_empty_calendar_is_not_worth_wiring():
    empty = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\nEND:VCALENDAR\r\n"
    ok, _ = build.describe_probe_response("ical", empty)
    assert not ok


def test_squarespace_events_collection_is_accepted():
    body = '{"items": [{"title": "A reading", "startDate": 4102444800000}]}'
    ok, description = build.describe_probe_response("squarespace", body)
    assert ok and "1 dated items" in description


def test_a_squarespace_blog_collection_is_rejected():
    # Same endpoint shape, no dates: that is a blog, not an events collection,
    # and wiring it would fill the board with essays.
    body = '{"items": [{"title": "A post"}, {"title": "Another"}]}'
    ok, _ = build.describe_probe_response("squarespace", body)
    assert not ok


def test_tribe_rest_is_accepted():
    ok, description = build.describe_probe_response("tribe", '{"events": [{"id": 1}]}')
    assert ok and "1 events" in description


def test_wp_rest_post_list_is_accepted():
    ok, description = build.describe_probe_response("wp-rest", '[{"id": 1}, {"id": 2}]')
    assert ok and "2 posts" in description


def test_html_served_at_a_json_endpoint_is_rejected():
    ok, description = build.describe_probe_response("squarespace", "<!DOCTYPE html>")
    assert not ok and description == "200 but not JSON"


def test_an_unknown_convention_type_is_never_accepted():
    ok, description = build.describe_probe_response("carrier-pigeon", "{}")
    assert not ok and "unknown convention type" in description


@pytest.mark.parametrize("kind", sorted(build.PROBE_TYPES))
def test_every_probe_type_is_judgeable(kind):
    # Garbage in, a verdict out — never an exception, or one bad response would
    # end a probe run partway through the venue list.
    ok, description = build.describe_probe_response(kind, "not remotely valid")
    assert not ok and description


def test_ids_are_stable_and_slugged():
    assert make_id("kgb-bar", "2026-09-20", "Prose night, three readers") == \
        "kgb-bar-2026-09-20-prose-night-three-readers"
