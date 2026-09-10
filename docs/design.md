# Two rooms

Glyph renders in one of two skins, declared per page on the root element:

    <html data-skin="paper">    reading rooms
    <html data-skin="board">    data rooms

That split is the whole visual argument. Writing is data, and the two deserve
different rooms — so the calendar gets a board and the poems get paper, and
neither has to pretend to be the other.

| | paper | board |
| --- | --- | --- |
| pages | index, poets, submit, about | calendar |
| ground | warm off-white `#f6f2ea` | near-black `#05070b` |
| ink | `#191512` | `#f5f5f7` |
| accent | oxblood `#8f2d22` | cyan `#42f5ff` |
| body face | serif, 17px, 1.65 leading | sans, 15px, 1.55 leading |
| dark mode | yes, via `prefers-color-scheme` | dark is the only mode |

## Why the board is dark only

It inherits the datarail.org palette exactly — the same cyan, the same
near-black, the same rule colour as `/events`. The family resemblance is the
point: someone who knows that board recognises this one. A board is a board, and
giving it a light mode would be a second design to keep honest for no gain.

Paper is light-first and does have a dark variant, because people read in bed.

## Typography rules that are not negotiable

- **A poem is rendered in `<pre>`.** The line breaks a poet sent are the poem.
  Nothing about responsive layout is worth reflowing them, so pieces wrap with
  `white-space: pre-wrap` and never at a width the writer did not choose.
- **The reading measure is 34em**, about 68 characters. Prose gets `.prose`;
  data does not need it.
- **Never scale a serif down to fit.** If a paper page is crowded, cut words.
- **The mono face is for data only** — times, prices, counts, filter chips,
  labels. It is the visual signal that you are looking at a record rather than
  at writing.

## The wordmark

`Glyph` set in the serif, followed by `¶ † ‡ §` in mono at 0.75rem: reference
marks, the marks a text carries in order to point at itself. They are the single
place the data metaphor is allowed to be literal, and it appears nowhere else —
no charts, no counters, no analysis. The metaphor sets the tone and then gets out
of the way.

The slogan — **The most beautiful kind of data** — sits beside the wordmark in
the header on every page except the landing one, in serif italic behind a hairline
rule, and folds away under 900px before it can crowd the nav. On the landing page
the hero says it at full size instead, so no page ever prints it twice.

## Adding a page

1. Pick a skin. If a person reads sentences on it, that is paper. If they scan
   rows, that is board.
2. Copy the header and colophon from the nearest existing page of that skin. The
   nav is duplicated markup on purpose: five static pages do not need a
   templating step, and a build step is a thing that can break between you and
   a poem.
3. Relative links only. The site is mounted at `datarail.org/glyph` today and
   should survive being moved without a find-and-replace.
4. No third-party requests. No fonts from a CDN, no analytics, no embeds. The
   about page promises this in writing, so it has to stay true.
