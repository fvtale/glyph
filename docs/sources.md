# What the venues actually publish

Findings from two probe rounds in CI and a follow-up from an ordinary
connection, 2026-09-10. Recorded here because the evidence otherwise lives in
an Actions log that expires, and re-running it costs each of these rooms a few
dozen requests for an answer we already have.

## The short version

**None of the fifteen venues publishes a usable machine-readable calendar.**
Not iCal, not Squarespace collection JSON, not The Events Calendar's REST
route, not the WordPress events post type, not schema.org JSON-LD on their
listing pages. The two RSS feeds that exist are dead: one is an archive of a
retired site, the other is empty.

The design assumption behind the feed layer — that most of these rooms run
Squarespace or WordPress and so publish `.ics` for free — was wrong. The probe
existed to test exactly that, and it did.

## GitHub Actions cannot reach several of them

Four venues that refused or ignored the prober in CI answered the same honest
`GlyphBot` user-agent normally from a residential connection: the Strand,
Greenlight, KGB Bar and Wendy's Subway. Their firewalls block cloud and
datacenter IP ranges wholesale. That is a generic defence, not a verdict on
Glyph — `robots.txt` permits us on every one of them.

It is still a no for anything running in Actions. **Do not route around it**:
no browser user-agent, no proxy services, no rotating addresses. The honest
options are asking the venue, or entering their listings by hand.

Poets House refuses from both places. Respect that outright.

## Per venue

| Venue | From Actions | From a normal connection | What is there |
| --- | --- | --- | --- |
| Nuyorican Poets Cafe | 200 HTML at `/calendar` | 200 | Custom page. No feed of any kind. |
| The Poetry Project | 200 HTML at `/events` | 200 | `/events/feed/` is RSS, but from the 2009–2019 site: links go to `2009-2019.poetryproject.org`, newest item February 2020. The current calendar is elsewhere. |
| Bowery Poetry | 404 on every route | 200, Squarespace | The events collection is not at `/events` or `/calendar`, and the homepage exposes no link to it. Worth finding the real slug: any Squarespace collection answers `?format=json`. |
| KGB Bar | Timed out | 200, WordPress | The REST index answers with a 301. Never tested properly, since CI gave up after two timeouts. |
| Franklin Park | Timed out | Unreachable | Looks down, not blocked. Retry later. |
| Housing Works Bookstore | 404 on every route | 200 | No feed found. |
| Poets House | 403 | 403 | Refuses automated requests outright. |
| Greenlight Bookstore | 403 | 200, Drupal | Tickets through Eventbrite. |
| Pete's Candy Store | 200 HTML at `/calendar` | 200 | Tickets through Dice and Eventbrite. |
| 92NY | 200 HTML at `/events` | 200 | Custom. No feed. |
| The Strand | 403 | 200 | Custom. Blocks datacenter ranges. |
| Wendy's Subway | Timed out | 200 | Blocks datacenter ranges. |
| Dixon Place | 200 HTML at `/calendar` | 200, WordPress | `/events/feed/` is valid RSS with zero items. Tickets through OvationTix. |
| The Astoria Bookshop | 200 HTML at `/events` | 200 | `/events/feed/` is a soft 404. |
| Bronx Library Center | 404 on every route | 200 | NYPL runs events centrally rather than per branch, so per-branch paths were never going to work. |

## What that means for the listings agent

The datarail.org/events feed works because Ticketmaster is one API covering
thousands of rooms. The NYC literary scene has no equivalent, and its rooms are
small, independently built, and mostly do not publish feeds. Scraping parity
with /events is not available for this set of venues.

The routes that remain, roughly in order of how much of the board each could
carry:

1. **Listings sent in.** Venues and series organisers email their dates; the
   agent drafts them into `curated.json` as a pull request for a person to
   approve. Consent-based, needs no scraping, and works for every room on this
   list including the ones that block bots. The `datarail-agents` email
   receptionist is most of the plumbing.
2. **Ticketing platforms.** Greenlight and Pete's sell through Eventbrite, Pete's
   also through Dice, Dixon Place through OvationTix. An adapter against a
   ticketing platform covers every venue that uses it, and those APIs are
   documented contracts.
3. **NYPL's central events system** for the library branches, which is one
   source for many rooms across three boroughs.
4. **Per-venue HTML adapters** for the reachable custom sites — Nuyorican, 92NY,
   Astoria Bookshop, Pete's. The most fragile option and the last resort: a
   theme redesign breaks one silently.
