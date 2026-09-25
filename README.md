# Folha do Clube

KOM/CR and Top 10 ranking for my running club, scraped daily from Strava, plus
running Best Efforts and Squadrats stats. Published with GitHub Pages.

Internal club tool: it reads Strava with my own session, with the members'
knowledge, once a day. It is not a general-purpose scraper.

Sister project: [kom-hunter](https://github.com/JustAnotherDud/kom-hunter)
started from the same `comum.py` and finds Run segments where a KOM looks
reachable.

## Site

`index.html` has three tabs:

- **KOMs & Top10s** reads `data.json`. Points: 11 minus the position (KOM = 10,
  10th = 1). Pace is computed in the page from `dist_km`, `tempo` and `tipo`
  (min/km, or km/h for Ride). On very short segments it can look odd.
- **Best Efforts** reads `prs.json` and highlights the best time per distance.
- **Squadrats** reads `squadrats.json` and `daily_gains.json` from
  [squadrats-club](https://github.com/JustAnotherDud/squadrats-club). Member
  colours also come from there (`membros_cores.json`).

## Data updates

`.github/workflows/update.yml` runs every day (cron 05:30 UTC, GitHub often
starts it later) and on `workflow_dispatch`. It runs `scrape.py` and
`scrape_prs.py` and commits the data files only if something besides `gerado`
changed. So "actualizado" on the site shows the last real change, not the
last run.

To run by hand:

```
STRAVA_SESSION=<cookie> python scrape.py
STRAVA_SESSION=<cookie> python scrape_prs.py
```

`STRAVA_SESSION` is the `_strava4_session` cookie (DevTools > Application >
Cookies > strava.com). When it expires the scripts exit with an error: copy a
fresh cookie into the Actions secret.

- `scrape.py` reads each member's `/segments/leader` pages and writes
  `data.json`. City and country come from the `<title>` of the public segment
  page and are cached in `localizacoes.json`. Delete an entry to fetch it again.
- `scrape_prs.py` reads the Run "Best Efforts" table from
  `/athletes/<id>/profile_sidebar_comparison` and writes `prs.json`. Efforts
  from activities Strava flagged (bad GPS) are dropped; the check is cached in
  `flagged.json`. These are not the manual "All-Time PRs", and Strava has no
  equivalent for Ride.
- Members are keyed by first name, or by a nickname in `ALCUNHAS`
  (`scrape.py`). Two members with the same first name would merge: give one
  of them a nickname.
- `ignorar.py <url-or-id> [reason]` adds a buggy segment to `IGNORAR` in
  `scrape.py`, pushes and starts the workflow.

## Tests

`tests/harness.py` checks that the scripts and the site behave as recorded in
`tests/baseline.json`. It makes no network requests: Strava is faked with
synthetic HTML and the site runs in Microsoft Edge through Playwright.

Setup, once:

```
python -m venv .venv
.venv/Scripts/pip install -r tests/requirements.txt
```

Run:

```
.venv/Scripts/python tests/harness.py
```

`--update` rewrites the baseline after an intended change. Without Edge, run
`playwright install chromium` and set `HARNESS_BROWSER=` (empty).
