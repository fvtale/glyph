/* =============================================================================
   Meter — the client side of the board.

   No framework, no build step, one file. Everything here is presentation: the
   listings arrive already validated by feed/build.py, so this code never has to
   defend itself against a malformed row, and it never invents a field a venue
   did not publish. An absent price renders as absent, not as "Free".

   Exposed as a single global because these pages are plain files served from a
   subdirectory, and a module graph would buy nothing.
   ============================================================================= */

(function () {
  "use strict";

  var KIND_LABELS = {
    reading: "Reading",
    openmic: "Open mic",
    workshop: "Workshop",
    launch: "Launch",
    panel: "Panel"
  };

  var REGION_LABELS = {
    manhattan: "Manhattan",
    brooklyn: "Brooklyn",
    queens: "Queens",
    bronx: "The Bronx",
    "staten-island": "Staten Island",
    "near-nj": "Near NJ",
    westchester: "Westchester",
    "long-island": "Long Island"
  };

  var DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  /* ---- helpers ----------------------------------------------------------- */

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // "2026-09-17" as a local date. Passing the string to Date() would parse it as
  // UTC midnight, which in New York is the evening before — every listing would
  // land on the wrong day for five hours of every day.
  function parseDay(iso) {
    var parts = String(iso).split("-");
    return new Date(+parts[0], +parts[1] - 1, +parts[2]);
  }

  function todayIso() {
    var now = new Date();
    var month = String(now.getMonth() + 1).padStart(2, "0");
    var day = String(now.getDate()).padStart(2, "0");
    return now.getFullYear() + "-" + month + "-" + day;
  }

  function dayOffset(iso) {
    var start = parseDay(todayIso());
    var target = parseDay(iso);
    return Math.round((target - start) / 86400000);
  }

  function formatDayHeading(iso) {
    var offset = dayOffset(iso);
    var date = parseDay(iso);
    var stamp = DAYS[date.getDay()] + " " + date.getDate() + " " + MONTHS[date.getMonth()];
    if (offset === 0) return '<span class="today">Tonight</span> &middot; ' + stamp;
    if (offset === 1) return "Tomorrow &middot; " + stamp;
    return stamp;
  }

  // 24-hour input, 12-hour output, because nobody in a bookshop says 19:30.
  function formatTime(value) {
    if (!value) return "";
    var parts = value.split(":");
    var hour = +parts[0];
    var minute = parts[1];
    var suffix = hour < 12 ? "AM" : "PM";
    var shown = hour % 12;
    if (shown === 0) shown = 12;
    return minute === "00" ? shown + " " + suffix : shown + ":" + minute + " " + suffix;
  }

  function isFree(listing) {
    return /^\s*free/i.test(listing.price || "");
  }

  /* ---- loading ----------------------------------------------------------- */

  // Sample data is invented, so it is never loaded by accident: the URL has to
  // ask for it, and anything rendered from it carries a banner.
  function sampleRequested() {
    return /(^|[?&])preview=sample(&|$)/.test(window.location.search);
  }

  function loadListings(root) {
    var base = root || "";
    var file = sampleRequested() ? "events.sample.json" : "events.json";
    return fetch(base + "data/" + file, { cache: "no-cache" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (payload) {
        payload.events = Array.isArray(payload.events) ? payload.events : [];
        return payload;
      });
  }

  /* ---- rendering --------------------------------------------------------- */

  function listingHtml(listing) {
    var kind = KIND_LABELS[listing.kind] || listing.kind;
    var where = escapeHtml(listing.venue);
    if (listing.neighborhood) {
      where += '<span class="dot">&middot;</span>' + escapeHtml(listing.neighborhood);
    }
    var end = listing.endTime ? "&ndash;" + formatTime(listing.endTime) : "";

    var html = '<article class="listing">';
    html += '<div class="when">' + formatTime(listing.time) + end + "</div>";
    html += '<div class="what"><h3><a href="' + escapeHtml(listing.url) +
            '" target="_blank" rel="noopener noreferrer">' +
            escapeHtml(listing.title) + "</a></h3>";
    html += '<div class="where">' + where + "</div></div>";

    html += '<div class="meta"><span class="tag tag--' + escapeHtml(listing.kind) + '">' +
            escapeHtml(kind) + "</span>";
    if (listing.price) html += '<span class="price">' + escapeHtml(listing.price) + "</span>";
    html += "</div>";

    if (listing.description) {
      html += '<p class="blurb">' + escapeHtml(listing.description) + "</p>";
    }
    if (listing.registration && listing.registration.deadline) {
      var reg = listing.registration;
      var bits = ["by " + escapeHtml(reg.deadline)];
      if (reg.sessions) bits.push(reg.sessions + " sessions");
      if (reg.capacity) bits.push(reg.capacity + " places");
      html += '<p class="note-reg">' + bits.join(" &middot; ") + "</p>";
    }
    if (listing.accessibility) {
      html += '<p class="note-access">' + escapeHtml(listing.accessibility) + "</p>";
    }
    html += "</article>";
    return html;
  }

  function groupByDay(listings) {
    var days = [];
    var index = {};
    listings.forEach(function (listing) {
      if (!index[listing.date]) {
        index[listing.date] = { date: listing.date, listings: [] };
        days.push(index[listing.date]);
      }
      index[listing.date].listings.push(listing);
    });
    days.sort(function (a, b) { return a.date < b.date ? -1 : 1; });
    return days;
  }

  function renderDays(target, listings) {
    if (!listings.length) {
      target.innerHTML =
        '<div class="empty"><h2>Nothing matches</h2>' +
        "<p>Loosen a filter, or widen the search. The board only ever holds what " +
        "a venue has actually announced.</p></div>";
      return;
    }
    target.innerHTML = groupByDay(listings).map(function (day) {
      return '<section class="daygroup"><h2>' + formatDayHeading(day.date) + "</h2>" +
             day.listings.map(listingHtml).join("") + "</section>";
    }).join("");
  }

  /* ---- the calendar page ------------------------------------------------- */

  function board(options) {
    var target = document.querySelector(options.target);
    var countEl = options.count ? document.querySelector(options.count) : null;
    var banner = options.banner ? document.querySelector(options.banner) : null;
    var state = { kinds: [], regions: [], free: false, query: "" };
    var all = [];

    function matches(listing) {
      if (state.kinds.length && state.kinds.indexOf(listing.kind) === -1) return false;
      if (state.regions.length && state.regions.indexOf(listing.region) === -1) return false;
      if (state.free && !isFree(listing)) return false;
      if (state.query) {
        var haystack = [listing.title, listing.venue, listing.neighborhood,
                        listing.description].join(" ").toLowerCase();
        if (haystack.indexOf(state.query) === -1) return false;
      }
      return true;
    }

    function apply() {
      var shown = all.filter(matches);
      renderDays(target, shown);
      if (countEl) {
        countEl.textContent = shown.length === all.length
          ? all.length + " listings"
          : shown.length + " of " + all.length;
      }
    }

    function wireChips(selector, key) {
      var buttons = document.querySelectorAll(selector);
      Array.prototype.forEach.call(buttons, function (button) {
        button.addEventListener("click", function () {
          var value = button.getAttribute("data-value");
          var on = button.getAttribute("aria-pressed") === "true";
          button.setAttribute("aria-pressed", on ? "false" : "true");
          if (key === "free") {
            state.free = !on;
          } else if (on) {
            state[key] = state[key].filter(function (item) { return item !== value; });
          } else {
            state[key] = state[key].concat([value]);
          }
          apply();
        });
      });
    }

    wireChips('[data-filter="kind"]', "kinds");
    wireChips('[data-filter="region"]', "regions");
    wireChips('[data-filter="free"]', "free");

    var search = options.search ? document.querySelector(options.search) : null;
    if (search) {
      search.addEventListener("input", function () {
        state.query = search.value.trim().toLowerCase();
        apply();
      });
    }

    loadListings(options.root).then(function (payload) {
      if (payload.sample && banner) {
        banner.hidden = false;
      }
      var today = todayIso();
      all = payload.events.filter(function (listing) {
        // Sample fixtures are allowed to be stale; a real board never shows the past.
        return payload.sample || listing.date >= today;
      });
      apply();
    }).catch(function (error) {
      target.innerHTML =
        '<div class="empty"><h2>No listings yet</h2>' +
        "<p>The board is built by the listings agent on a schedule. It has not " +
        "written a file here yet, or this page is open from disk where it cannot " +
        "read one.</p>" +
        '<p class="count">' + escapeHtml(error.message) + "</p></div>";
    });
  }

  /* ---- the landing page's short list ------------------------------------ */

  function upcoming(options) {
    var target = document.querySelector(options.target);
    if (!target) return;
    loadListings(options.root).then(function (payload) {
      var today = todayIso();
      var soon = payload.events
        .filter(function (listing) { return payload.sample || listing.date >= today; })
        .slice(0, options.limit || 6);
      if (payload.sample) {
        var banner = options.banner && document.querySelector(options.banner);
        if (banner) banner.hidden = false;
      }
      renderDays(target, soon);
    }).catch(function () {
      target.innerHTML =
        '<div class="empty"><h2>The board is still being wired up</h2>' +
        "<p>Venue by venue, each one verified before it is trusted. Nothing is " +
        "listed here until a venue has actually announced it.</p></div>";
    });
  }

  /* ---- the coverage table ----------------------------------------------- */

  function coverage(options) {
    var target = document.querySelector(options.target);
    if (!target) return;
    loadListings(options.root).then(function (payload) {
      var regions = (payload.coverage && payload.coverage.regions) || {};
      var keys = Object.keys(REGION_LABELS);
      var rows = keys.map(function (key) {
        var row = regions[key] || { venues: 0, wired: 0, listings: 0 };
        var zero = row.venues === 0 ? " zero" : "";
        return "<tr><td>" + escapeHtml(REGION_LABELS[key]) + "</td>" +
               '<td class="num' + zero + '">' + (row.venues || 0) + "</td>" +
               '<td class="num' + zero + '">' + (row.wired || 0) + "</td>" +
               '<td class="num' + zero + '">' + (row.listings || 0) + "</td></tr>";
      }).join("");
      target.innerHTML =
        '<table class="datatable"><thead><tr><th>Region</th>' +
        "<th>Venues known</th><th>Feeds verified</th><th>Listings live</th>" +
        "</tr></thead><tbody>" + rows + "</tbody></table>";
    }).catch(function () {
      target.innerHTML =
        '<p class="count">Coverage figures come from the generated board, ' +
        "which is not readable from here yet.</p>";
    });
  }

  window.Meter = {
    board: board,
    upcoming: upcoming,
    coverage: coverage,
    load: loadListings,
    kinds: KIND_LABELS,
    regions: REGION_LABELS
  };
})();
