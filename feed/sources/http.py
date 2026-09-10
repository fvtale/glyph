"""Polite HTTP for every adapter.

Meter reads other people's calendars. The cost of that has to land on Meter, not
on a 45-seat reading room's web host, so all fetching goes through here:

- one identifiable User-Agent naming the project and where to complain
- robots.txt honoured per host, fetched once and cached
- at most one request per host per second, process-wide
- hard timeouts, so a hanging venue cannot hold the whole run open
"""

from __future__ import annotations

import time
import urllib.robotparser
from urllib.parse import urlsplit, urlunsplit

import requests

from .base import SourceError

USER_AGENT = (
    "MeterBot/0.1 (+https://datarail.org/meter/about.html) "
    "NYC literary events index; contact contact@datarail.org"
)
TIMEOUT = 20
MIN_INTERVAL = 1.0          # seconds between requests to the same host

_last_hit: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _host_key(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _robots_for(url: str) -> urllib.robotparser.RobotFileParser | None:
    """Fetch and cache a host's robots.txt.

    A host with no robots.txt, or one we cannot read, is treated as permissive —
    that is the convention, and inventing a prohibition would just silently
    empty the board.
    """
    root = _host_key(url)
    if root in _robots:
        return _robots[root]
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(f"{root}/robots.txt")
    try:
        response = requests.get(
            f"{root}/robots.txt", timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
        )
        if response.status_code >= 400:
            _robots[root] = None
            return None
        parser.parse(response.text.splitlines())
    except requests.RequestException:
        _robots[root] = None
        return None
    _robots[root] = parser
    return parser


def allowed(url: str) -> bool:
    parser = _robots_for(url)
    if parser is None:
        return True
    return parser.can_fetch(USER_AGENT, url)


def _throttle(url: str) -> None:
    root = _host_key(url)
    previous = _last_hit.get(root)
    if previous is not None:
        wait = MIN_INTERVAL - (time.monotonic() - previous)
        if wait > 0:
            time.sleep(wait)
    _last_hit[root] = time.monotonic()


def polite_get(url: str) -> str:
    """Fetch a URL as text, or raise SourceError. Never raises anything else."""
    # Strip fragments; they mean nothing to a server and pollute the robots check.
    parts = urlsplit(url)
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))

    if parts.scheme not in ("http", "https"):
        raise SourceError(f"refusing non-http url: {url}")
    if not allowed(url):
        raise SourceError(f"robots.txt disallows {url}")

    _throttle(url)
    try:
        response = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    except requests.RequestException as exc:
        raise SourceError(f"{url}: {exc}") from exc
    if response.status_code >= 400:
        raise SourceError(f"{url}: HTTP {response.status_code}")
    return response.text
