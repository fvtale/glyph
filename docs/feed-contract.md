# The listing contract

Everything in `public/data/events.json` conforms to this. `feed/build.py`
rejects anything that does not, and the page assumes it never has to defend
itself against a malformed listing.

## A listing

```json
{
  "id": "poetry-project-2026-09-17-notley-reading",
  "title": "Alice Notley and Anselm Berrigan",
  "kind": "reading",
  "date": "2026-09-17",
  "time": "20:00",
  "endTime": "21:30",
  "venueId": "poetry-project",
  "venue": "The Poetry Project",
  "neighborhood": "East Village",
  "region": "manhattan",
  "writers": ["alice-notley"],
  "price": "$10",
  "age": "All ages",
  "accessibility": "Not step-free — sanctuary is up one flight",
  "description": "Two readers, thirty minutes each, questions after.",
  "url": "https://www.poetryproject.org/events/...",
  "source": "poetry-project",
  "firstSeen": "2026-09-01"
}
```

### Required

`id`, `title`, `kind`, `date`, `time`, `venue`, `venueId`, `region`, `url`,
`source`. A listing missing any of these is dropped, because each one is load-
bearing for either rendering or trust:

- **`id`** — stable across runs, so a listing keeps its `firstSeen` and does not
  flicker in and out of "new this week". Built as `<venueId>-<date>-<slug>`.
  A source that changes an event's id every fetch is a bug in the adapter.
- **`url`** — the venue's own page for the event, never Glyph's. It is the
  authority; Glyph is an index. A listing with nowhere to link is not publishable.
- **`source`** — the adapter that produced it, or `curated`. Determines which
  existing listings a successful run may replace, and shows up in the coverage
  block.
- **`venueId`** — joins `public/data/venues.json`. A listing naming a venue that
  is not in the registry is dropped; adding coverage means adding the venue
  first, deliberately.

### `kind`

One of five. The taxonomy is closed because the filter chips are, and because
"other" is where a taxonomy goes to die.

| kind | what it covers |
| --- | --- |
| `reading` | featured readers, series, launches that are really just readings |
| `openmic` | open mics, slams, sign-up nights |
| `workshop` | generative workshops, craft classes, multi-week courses, manuscript groups |
| `launch` | book launches, signings, author tour stops |
| `panel` | craft talks, panels, interviews, prose and storytelling nights |

### `region`

Glyph claims the full metro area: `manhattan`, `brooklyn`, `queens`, `bronx`,
`staten-island`, `near-nj` (Jersey City, Hoboken, Newark), `westchester`,
`long-island`.

Claiming a region is not the same as covering it, and thin coverage of a region
reads worse than not claiming it. So the builder writes a `coverage` block
saying, per region, how many venues are registered and how many have a verified
feed — and `about.html` prints it. The honest position is visible on the site
rather than implied by an empty filter.

### Optional

`endTime`, `neighborhood`, `writers`, `price`, `age`, `accessibility`,
`description`, `registration`.

**`price`** is a display string, not a number: `Free`, `$10`, `$10–15`,
`$20 suggested`, `See link`. Doors have too many pricing models to normalize and
a wrong number is worse than a string.

**`accessibility`** is optional and, when present, quoted from the venue rather
than inferred. Several of these rooms are up a flight of stairs; guessing is not
acceptable, so absent means unknown, not accessible.

**`registration`** appears on workshops only, where the deadline matters more
than the start time:

```json
"registration": { "deadline": "2026-09-10", "sessions": 4, "capacity": 12, "url": "https://..." }
```

## The file

```json
{
  "generatedAt": "2026-09-10T14:03:02+00:00",
  "sample": false,
  "coverage": {
    "regions": { "manhattan": { "venues": 9, "wired": 0, "listings": 0 } },
    "sources": { "poetry-project": { "ok": true, "count": 12, "fetchedAt": "..." } }
  },
  "events": []
}
```

`sample` is `true` only in `events.sample.json`. The page renders a permanent
banner whenever it is showing a file with that flag set, and sample data is
never loaded unless the URL explicitly asks for it (`?preview=sample`). Design
work should never be able to leak invented listings onto a live board.

## Validation rules

Beyond required fields:

- `date` matches `YYYY-MM-DD`, `time` and `endTime` match `HH:MM`.
- Nothing in the past, nothing beyond `MAX_HORIZON_DAYS` (240) — a date years out
  is a parsing bug, not a listing.
- `kind` and `region` are in their closed sets; `venueId` is in the registry.
- `url` is `http(s)` and absolute.
- `MAX_EVENTS` (400) caps the board, because the page renders every row.

## Dedupe

Key is `(date, venueId, normalized title)` — case-folded, accent-stripped,
punctuation-collapsed. Curated always wins. Between two scraped listings, the
first source in `sources/__init__.py` order wins, which makes precedence
explicit rather than incidental.

A recurring series expanded from an iCal `RRULE` produces one listing per
occurrence inside the horizon. That is intentional: an open mic every Monday is
eight listings a person can plan around, not one row saying "weekly".
