"""Generic iCal adapter.

Most of the rooms on this list run Squarespace, WordPress with The Events
Calendar, or a Google Calendar, and all three publish .ics. One adapter that
speaks iCal well therefore covers more venues than a pile of bespoke HTML
parsers, and it breaks far less often — an .ics feed is a contract, a theme
redesign is not.

Each venue's entry in feed/feeds.json supplies the URL and a kind fallback; the
adapter itself holds no venue-specific knowledge.
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, time as time_cls, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from icalendar import Calendar

from .base import NYC_TZ, Source, SourceError, clean_text, infer_kind, make_id
from .http import polite_get

NY = ZoneInfo(NYC_TZ)


def _local_naive(value) -> datetime | None:
    """DTSTART/DTEND -> naive New York datetime.

    Returns None for an all-day entry (a bare date), which this adapter refuses
    to publish: the contract requires a start time, and inventing 19:00 for a
    venue that did not say so would send someone to a locked door.
    """
    if isinstance(value, datetime):          # must precede date; datetime is a date
        if value.tzinfo is not None:
            return value.astimezone(NY).replace(tzinfo=None)
        return value
    return None


def _excluded(component) -> set[datetime]:
    """EXDATE values, flattened. Cancelled weeks of a recurring series."""
    raw = component.get("EXDATE")
    if raw is None:
        return set()
    entries = raw if isinstance(raw, list) else [raw]
    out: set[datetime] = set()
    for entry in entries:
        for item in getattr(entry, "dts", []):
            moment = _local_naive(item.dt)
            if moment is not None:
                out.add(moment)
    return out


def _first(component, *names: str) -> str:
    for name in names:
        value = component.get(name)
        if value:
            return str(value)
    return ""


class IcalSource(Source):
    def __init__(self, venue: dict, config: dict, horizon_days: int = 240) -> None:
        self.venue = venue
        self.venue_id = venue["id"]
        self.name = config.get("source") or venue["id"]
        self.url = config["url"]
        self.kind_fallback = config.get("kindFallback", "reading")
        self.horizon_days = horizon_days
        #: Occurrences dropped for want of a start time. Reported by build.py so
        #: lost coverage is visible rather than silent.
        self.skipped_all_day = 0

    def fetch(self) -> list[dict]:
        text = polite_get(self.url)
        try:
            calendar = Calendar.from_ical(text)
        except Exception as exc:                      # icalendar raises broadly
            raise SourceError(f"{self.url}: not parseable as iCal ({exc})") from exc

        window_start = datetime.combine(date_cls.today(), time_cls(0, 0))
        window_end = window_start + timedelta(days=self.horizon_days)

        listings: list[dict] = []
        for component in calendar.walk("VEVENT"):
            if str(component.get("STATUS") or "").upper() == "CANCELLED":
                continue
            listings.extend(self._occurrences(component, window_start, window_end))
        if not listings:
            raise SourceError(f"{self.url}: parsed but produced no usable listings")
        return listings

    def _occurrences(self, component, window_start, window_end) -> list[dict]:
        dtstart = component.get("DTSTART")
        if dtstart is None:
            return []
        start = _local_naive(dtstart.dt)
        if start is None:
            self.skipped_all_day += 1
            return []

        dtend = component.get("DTEND")
        end = _local_naive(dtend.dt) if dtend is not None else None
        duration = (end - start) if end and end > start else None

        starts = [start]
        rule = component.get("RRULE")
        if rule is not None:
            try:
                expanded = rrulestr(
                    f"RRULE:{rule.to_ical().decode('utf-8')}", dtstart=start
                )
                starts = expanded.between(window_start, window_end, inc=True)
            except Exception as exc:
                raise SourceError(f"{self.url}: bad RRULE ({exc})") from exc
            skip = _excluded(component)
            starts = [moment for moment in starts if moment not in skip]

        title = clean_text(_first(component, "SUMMARY"), 160)
        if not title:
            return []
        description = clean_text(_first(component, "DESCRIPTION"))
        url = _first(component, "URL") or self.venue.get("site", "")
        kind = infer_kind(title, description, self.kind_fallback)

        out: list[dict] = []
        for moment in starts:
            if not (window_start <= moment <= window_end):
                continue
            day = moment.date().isoformat()
            listing = {
                "id": make_id(self.venue_id, day, title),
                "title": title,
                "kind": kind,
                "date": day,
                "time": moment.strftime("%H:%M"),
                "venueId": self.venue_id,
                "venue": self.venue["name"],
                "neighborhood": self.venue.get("neighborhood", ""),
                "region": self.venue["region"],
                "writers": [],
                "description": description,
                "url": url,
                "source": self.name,
            }
            if duration is not None:
                listing["endTime"] = (moment + duration).strftime("%H:%M")
            out.append(listing)
        return out
