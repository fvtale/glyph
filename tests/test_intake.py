"""Tests for the listing intake judge.

feed/intake.py decides whether a listing sent in by email opens as a one-click
pull request or as a draft with problems at the top. A false clean puts a bad
listing one click from the board; a false problem makes a good venue wait. Both
are tested here, without git or a network.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "feed"))

import intake                                     # noqa: E402

VENUES = {
    "kgb-bar": {"id": "kgb-bar", "name": "KGB Bar", "region": "manhattan",
                "site": "https://www.kgbbar.com"},
}
NEXT_WEEK = (date.today() + timedelta(days=7)).isoformat()


def listing(**overrides) -> dict:
    """A listing file exactly as the receptionist writes one.

    Note what is absent: `source`. The board builder stamps that on approved
    listings as it reads them, so real files never carry it. This fixture once
    did, which is how the tests stayed green while every genuine proposal
    opened as a draft for "missing source".
    """
    base = {
        "id": f"kgb-bar-{NEXT_WEEK}-prose-night",
        "title": "Prose night",
        "kind": "reading",
        "date": NEXT_WEEK,
        "time": "19:00",
        "venue": "KGB Bar",
        "venueId": "kgb-bar",
        "neighborhood": "East Village",
        "region": "manhattan",
        "writers": [],
        "url": "https://www.kgbbar.com/events/prose-night",
        "price": "Free",
    }
    base.update(overrides)
    return base


def judge(*items, existing=()):
    proposed = [(f"{item['id']}.json" if isinstance(item, dict) else "broken.json", item)
                for item in items]
    return intake.review(proposed, VENUES, list(existing))


# ---------------------------------------------------------------------------
# the verdict
# ---------------------------------------------------------------------------

def test_a_complete_listing_is_clean():
    verdicts = judge(listing())
    assert intake.is_clean(verdicts)
    assert verdicts[0].problems == []


def test_a_file_with_no_source_is_judged_as_the_board_will_see_it():
    # Regression, found by the first end-to-end run: the judge checked the raw
    # file, which never carries a source, and so failed every real proposal
    # for a field the builder always supplies. The one-click path never ran.
    item = listing()
    assert "source" not in item
    verdicts = judge(item)
    assert "missing source" not in verdicts[0].problems
    assert intake.is_clean(verdicts)


def test_a_listing_in_the_past_is_a_problem_for_a_new_proposal():
    # For a fresh submission, last week is a typo in the year.
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    item = listing(date=yesterday, id=f"kgb-bar-{yesterday}-prose-night")
    verdicts = judge(item)
    assert not intake.is_clean(verdicts)
    assert "in the past" in verdicts[0].problems


def test_an_unknown_venue_is_a_problem():
    item = listing(venueId="cornelia-street", id=f"cornelia-street-{NEXT_WEEK}-prose-night")
    assert "registry" in " ".join(judge(item)[0].problems)


def test_a_missing_time_is_a_problem():
    item = listing()
    del item["time"]
    assert "missing time" in judge(item)[0].problems


def test_a_file_that_is_not_an_object_is_a_problem():
    verdicts = judge(["not", "an", "object"])
    assert verdicts[0].problems == ["not a JSON object"]
    assert not intake.is_clean(verdicts)


def test_a_file_named_differently_from_its_id_is_a_problem():
    verdicts = intake.review([("something-else.json", listing())], VENUES, [])
    assert any("file name" in problem for problem in verdicts[0].problems)


def test_a_listing_already_on_the_board_is_a_duplicate():
    existing = [listing(id="kgb-bar-older-id", title="PROSE NIGHT!")]
    verdicts = judge(listing(), existing=existing)
    assert any("duplicate of kgb-bar-older-id" in problem for problem in verdicts[0].problems)


def test_a_reused_id_is_a_problem():
    verdicts = judge(listing(), existing=[listing()])
    assert "that id is already on the board" in verdicts[0].problems


def test_an_empty_proposal_is_never_clean():
    assert not intake.is_clean([])


def test_one_bad_listing_makes_the_whole_proposal_a_draft():
    good = listing()
    bad = listing(id=f"kgb-bar-{NEXT_WEEK}-other", title="Other", kind="concert")
    assert not intake.is_clean(judge(good, bad))


# ---------------------------------------------------------------------------
# links
# ---------------------------------------------------------------------------

def test_a_link_to_the_venue_itself_is_fine():
    assert intake.link_warning("https://kgbbar.com/x", VENUES["kgb-bar"]) is None


def test_a_link_to_a_known_ticket_seller_is_fine():
    assert intake.link_warning("https://www.eventbrite.com/e/123", VENUES["kgb-bar"]) is None
    assert intake.link_warning("https://dice.fm/event/abc", VENUES["kgb-bar"]) is None


def test_a_link_anywhere_else_is_flagged_but_not_blocked():
    item = listing(url="https://totally-legit-tickets.example/kgb")
    verdict = judge(item)[0]
    assert verdict.problems == []
    assert any("totally-legit-tickets.example" in warning for warning in verdict.warnings)


def test_a_lookalike_domain_is_not_mistaken_for_the_venue():
    # kgbbar.com.evil.example ends with the venue's name but is not its site.
    assert intake.link_warning("https://kgbbar.com.evil.example/", VENUES["kgb-bar"])


def test_a_missing_price_is_a_warning_not_a_problem():
    item = listing()
    del item["price"]
    verdict = judge(item)[0]
    assert verdict.problems == []
    assert any("price" in warning for warning in verdict.warnings)


# ---------------------------------------------------------------------------
# the pull request text
# ---------------------------------------------------------------------------

def test_the_body_says_ready_when_clean():
    body = intake.compose_body(judge(listing()), notes="")
    assert body.startswith("## Ready to merge")
    assert "[Prose night](https://www.kgbbar.com/events/prose-night)" in body


def test_the_body_leads_with_problems_when_not_clean():
    item = listing(kind="concert")
    body = intake.compose_body(judge(item), notes="")
    assert body.startswith("## Needs attention")
    assert "unknown kind" in body


def test_a_pipe_in_a_title_cannot_break_the_table():
    body = intake.compose_body(judge(listing(title="Poems | Prose\nNight")), notes="")
    row = next(line for line in body.splitlines() if "Poems" in line)
    assert row.count("|") == 7      # six columns, no extra cells smuggled in


def test_the_receptionist_notes_are_included():
    body = intake.compose_body(judge(listing()), notes="Time was given as 'evening'.")
    assert "Time was given as 'evening'." in body


def test_the_title_is_one_bounded_line():
    # It is written to GITHUB_OUTPUT, where a newline would let submitted text
    # define outputs of its own.
    title = intake.pr_title("Listing: a\nclean=true\n" + "x" * 500, [])
    assert "\n" not in title
    assert len(title) <= intake.TITLE_LIMIT


def test_an_empty_subject_gets_a_sensible_title():
    assert intake.pr_title("", judge(listing(), listing(id="b", title="B"))) == \
        "Listing proposal (2 listings)"


def test_times_render_the_way_people_say_them():
    assert intake.when_text({"date": "2026-09-17", "time": "19:30"}).endswith("7:30 PM")
    assert intake.when_text({"date": "2026-09-17", "time": "20:00"}).endswith("8 PM")
