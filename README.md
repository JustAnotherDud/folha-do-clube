# Folha do Clube

Daily KOM/CR and Top-10 ranking for my running club, scraped from Strava's
`/segments/leader` pages — plus running Best Efforts and Squadrats stats.
Published via GitHub Pages.

Internal club tool: it reads Strava through my own authenticated session, with
the members' knowledge, at a daily cron cadence — not a general-purpose
scraper.

Sister project:
[kom-hunter](https://github.com/JustAnotherDud/kom-hunter) — same code origin
(`comum.py`), different purpose: finds Run segments where a KOM looks
reachable.

## How the data is updated

**Automatic**, two workflows. `.github/workflows/update.yml` runs every day at
05:30 UTC (and on `workflow_dispatch`), `scrape.py` + `scrape_prs.py`.
`.github/workflows/update-activities.yml` runs `scrape_activities.py` on its
own, 4x/day (every 6h): see the "Club activity feed" section below for why
it needs a tighter cadence than the rest. Both only commit/push if something
actually changed. Nothing to do by hand day to day.

Manual, only to force an update outside the cron window or to test locally:

```
STRAVA_SESSION=<_strava4_session cookie> python scrape.py
STRAVA_SESSION=<_strava4_session cookie> python scrape_prs.py
STRAVA_SESSION=<_strava4_session cookie> python scrape_activities.py
```

`STRAVA_SESSION` is the authenticated session cookie (DevTools → Application →
Cookies → strava.com → `_strava4_session`). Renew it manually when it expires.

Ranking points: position 1 = 10 pts … position 10 = 1 pt (11 − position).

## City/country + pace fields

`scrape.py` also fills `cidade` and `pais` per row, from the `<title>` of the
public `/segments/<id>` page (no login needed). The result is cached in
`localizacoes.json` — Strava is only asked for what isn't already there, so
it's worth keeping that file versioned (the workflow already commits it). To
force a re-fetch of a segment, delete its entry in that file.

`tempo` always comes normalised to `M:SS` or `H:MM:SS` (it used to be mixed,
e.g. `"25s"` vs `"2:29"`). Pace (min/km for Run/Walk/Trail Run, km/h for Ride)
is computed in `index.html` from `dist_km` + `tempo` + `tipo` — it is not
stored in `data.json`. Note: for very short segments (sprints/ramps <300m) the
computed pace isn't very representative, so it's normal for it to look odd.

Shared logic between `scrape.py` and `scrape_prs.py` lives in `comum.py`.

## Running Best Efforts / PRs (`scrape_prs.py`)

Extracts the "Best Efforts" widget from each athlete's profile sidebar and
writes `prs.json` — the same table the club used to maintain by hand in a
spreadsheet. The `/athletes/<id>` page is React (the table comes in via JS,
it's not in the served HTML), so the data comes from the AJAX endpoint
`/athletes/<id>/profile_sidebar_comparison?hl=en-GB`, which only responds with
the `X-Requested-With: XMLHttpRequest` header. Runs with the same session as
`scrape.py`.

This is not the "All-Time PRs" (those are filled in manually by the athlete)
and it doesn't cover bike — Strava has no aggregated Best-Efforts-by-distance
widget for Ride, only the Power Curve, which is a different thing. `index.html`
shows the result in a "Best Efforts 🏃" table below the KOM ranking, with the
best time per distance highlighted; it loads `prs.json` optionally — the KOM
page keeps working before the script's first run (file doesn't exist yet).

## Club activity feed (`scrape_activities.py`)

Writes `activities.json`: one row per activity (athlete, type, start time,
duration, distance, pace), only for the 5 athletes also tracked by
[squadrats-club](https://github.com/JustAnotherDud/squadrats-club): the
running club has 10 members, the other 5 aren't relevant there. Consumed by
squadrats-club's own pipeline (`raw.githubusercontent.com/.../main/data/
activities.json`, same cross-repo pattern it already uses in reverse for
`squadrats.json`/`daily_gains.json`) to line activities up against
squadratinhos gains.

Source: `/clubs/<club_id>/feed?club_id=<id>&feed_type=club&num_entries=N`, the
JSON API behind the club's "Recent Activity" page (React): not HTML to
scrape like `scrape.py`, not an AJAX HTML fragment like `scrape_prs.py`, a
clean JSON payload with `athlete`, `type`, `startDate` (ISO-8601 UTC, to the
second), `elapsedTime` (seconds), and `stats` (distance/pace as marked-up
text, parsed the same way `scrape.py` parses `<td>` cells). Not publicly
documented by Strava; found by inspecting the authenticated session
(2026-09-12), see the script's docstring for the exact field names.

The API's `page`/`before` pagination didn't reproduce in manual testing, so
the script always fetches the club's latest `N=20` activities (the whole
10-member club, not just the 5 tracked) and **merges** them into
`activities.json` by id instead of replacing it: old rows that fall out of
that window stay. History accumulates run by run, same idea as
squadrats-club's `append_events.py`.

**Second source, per-athlete profile.** With 10 members competing for the
same 20 club-feed slots, a less active athlete gets crowded out entirely
(one of the 5 tracked showed up zero times in a real test). `/athletes/<id>`
has no `/feed` endpoint of its own (tried every parameter combination that
worked for the club, all 404), but the profile page itself ships with a
`data-react-props` attribute (server-side React hydration, same mechanism
the rest of the site uses) holding `appContext.preFetchedEntries`, the same
`activity` shape as the club feed. Most pre-fetched entries aren't
activities (they're "Challenge" cards, Strava's badge/challenge noise),
filtered by `entity == "Activity"`. No pagination at all here either
(no "load more" control on the page); typically 1-4 activities per athlete,
but every one of the 5 always gets its own slice, unlike the club feed.

Both sources feed the same merge, deduplicated by id.

**It wasn't rare enough.** Real data made the gap concrete: Pedro's profile
showed 19 activities in the last 4 weeks (Strava's own "Total Activities"
count, ~0.7/day), but with the scraper running once a day, only 2-3 ever
made it into `activities.json`: about 84% silently lost, because both
windows are small (club feed: ~2 slots per athlete once split 10 ways;
profile: typically 2-4, mostly crowded out by "Challenge" cards) and neither
paginates backward. Once something falls out, it's gone for good, not just
late.

**Mitigation (2026-09-13): a dedicated, more frequent cron for this script
only**, `update-activities.yml`, 4x/day instead of 1x/day, **not** touching
`scrape.py`/`scrape_prs.py`'s cadence or request budget (they're a separate
workflow, separate schedule, separate concern). At 4x/day an activity is
only lost if the same athlete posts more than the window holds *within 6h*,
not within 24h. Pedro's actual pattern (bursty but well under that in any
6h stretch) would have been almost entirely captured. Cost: 6 requests per
run (1 club feed + 5 profiles, same session, `PAGE_DELAY` between them) vs.
the tens-to-hundreds `scrape.py` already makes in one daily run: a small
addition on the same authenticated session, not a new risk category.
GitHub Actions minutes are free either way (public repo).

**This does not fix the underlying limit.** Still no way to page backward in
either source; 4x/day only shrinks the *window* in which an activity can be
lost, it doesn't remove the cap. An athlete bursty enough within a single 6h
stretch (several activities logged close together) can still lose some.
Treat this as "day-to-day coverage, much improved", not "complete history",
which was never the goal.
