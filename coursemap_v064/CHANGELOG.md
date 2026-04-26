## [0.6.4] — 2026-04-26

### Fixed

- **Campus/mode error now suggests valid combinations** — when a student picks an
  invalid campus/mode pair (e.g. `D/INT`), the error message now lists the valid
  options ranked by course availability: `Valid combinations for this major: D/DIS, A/INT, M/INT`.
- **`ALLOWED_ORIGINS` env var for CORS** — production deployments can now lock CORS
  to a specific domain via `ALLOWED_ORIGINS="https://yourdomain.com"` instead of the
  open `*` default.

### Added

- **`DEPLOYMENT.md`** — comprehensive deployment guide covering Fly.io (free tier,
  recommended), Docker Compose on a VPS, local dev, dataset refresh workflow,
  environment variables, resource requirements, and a production security checklist.
- **`fly.toml`** — Fly.io deployment config targeting `syd` region (Sydney, closest
  to NZ). Includes auto-stop/start for zero idle cost, health checks, and shared-CPU
  free-tier sizing.
- **Improved `Dockerfile`** — `WORKERS` env var support, `curl`-based `HEALTHCHECK`
  directive, cleaner CMD using shell form for env var expansion.
- **Improved `docker-compose.yaml`** — `ALLOWED_ORIGINS` and `WORKERS` env vars,
  dataset bind-mount (`./datasets:/app/datasets:ro`) so data can be refreshed without
  rebuilding the image, structured log rotation.

## [0.6.3] — 2026-04-26

### Added

- **`coursemap data-quality` CLI command** — prints a full structured report showing:
  - Dataset scrape date and staleness status
  - Prerequisite format distribution (null / flat-list old-scraper / AND-OR structured)
  - Courses with real prerequisites after the plausibility filter
  - Level distribution histogram
  - Major qualification type breakdown (undergrad vs postgrad)
  - Cross-subject prerequisites lost to the plausibility filter
  - Actionable recommendations with estimated re-scrape time
- **`/api/data-quality` REST endpoint** — same information as JSON for the UI and CI health checks.
- **`--only-missing` flag for `refresh_prerequisites`** — skips courses already using structured AND/OR format, enabling fast incremental updates after a partial re-scrape run.

### Key finding documented

All 2766 courses are still using the **old flat-list prerequisite format** from the original regex scraper. The new HTML-aware scraper exists and is correct, but has never been run against the full dataset. Running `python -m coursemap.ingestion.refresh_prerequisites` (~1 minute) would:
- Upgrade all courses to structured AND/OR prerequisite trees
- Recover cross-subject prerequisites (currently all dropped by the plausibility filter — ~2758 courses affected)
- Reduce `prerequisites=None` from 1948 courses (70%) to a much smaller number
- Dramatically improve plan accuracy for courses with OR-logic or cross-subject prerequisites

## [0.6.2] — 2026-04-26

### Added

- **Qualification-type filter in major selector** (UI) — a "All qualifications" dropdown above the major search field lets students filter by degree type (Bachelor of Science, Bachelor of Arts, Master of Science, etc.). The qualification type is parsed from the major name server-side and returned by `/api/majors` as `qualification_type`. Autocomplete suggestions now show the degree type as a subtitle.
- **Prerequisite coverage warning** (UI) — when a generated plan contains level-200+ courses whose prerequisite data hasn't been scraped (coverage < 95%), an amber collapsible banner appears below the stats grid listing the affected course codes, each linking to Massey's course search so students can verify manually. Dismissable per-session.
- **`prereq_data_available` flag per course** — every course object in `/api/plan` responses now includes `prereq_data_available: bool` indicating whether prerequisite data exists for that course. Clients can use this to surface per-course warnings.
- **`prereq_coverage` in plan meta** — plan responses now include `meta.prereq_coverage: {total_courses, courses_with_data, coverage_pct, missing_data_codes}` summarising prerequisite data completeness for the scheduled plan. `missing_data_codes` lists level-200+ courses lacking data (capped at 20).

### Improved

- **HTML export completely overhauled** — the downloaded HTML plan now includes: prerequisite text per course, double-major SHARED/2ND badges, per-course ⚠ markers for unverified prerequisites with a coverage caveat block, a legend for double-major colour coding, proper `@media print` CSS for clean browser printing, and a disclaimer footer. Files are named with the full plan title including double-major label.
- **`/api/majors` returns `qualification_type`** — allows clients to filter and group majors by degree type without re-parsing the name.

## [0.6.1] — 2026-04-26

### Fixed

- **`--auto-fill` + `--double-major` CLI guard removed** — `generate_filled_double_major_plan()` was already fully implemented and wired in the API; only the CLI blocked it with an unnecessary error. Both flags can now be combined directly: `coursemap plan --major X --double-major Y --auto-fill`.
- **`--start-semester` CLI flag added** — the UI's start-semester dropdown had no CLI equivalent; `--start-semester {S1,S2,SS}` is now a first-class flag. Defaults to the current semester auto-detected from the system date (Feb–Jun → S1, Jul–Oct → S2, Nov–Jan → SS). `--start-year` likewise defaults to the current year instead of the hardcoded 2026.
- **`start_semester` wired into all CLI dispatch paths** — all four `generate_*` call sites in `_cmd_plan` now pass `start_semester=getattr(args, "start_semester", None)`.
- **Explain endpoint "earliest possible semester" accuracy** — the previous `chain_depth + 1` estimate ignored offering constraints. A chain-depth-4 course offered only in S1, whose last prerequisite finishes in S2, now correctly reports "earliest possible semester: 6" instead of "5". The calculation walks the S1→S2→SS cycle forward from the post-prerequisite slot until it finds a slot matching the course's actual offerings.
- **`pyproject.toml` version** — was `0.3.0`, now correctly `0.6.0`.

### Added

- **Saved plans panel** (UI) — a "Saved plans" section in the sidebar lets students save, load, rename, and delete up to 20 named plans using `localStorage`. Each entry shows the plan name, semester count, and total credits. Loading a plan restores the form parameters so the configuration is reproducible. A toast notification confirms save/load actions.
- **Monthly dataset refresh GitHub Actions workflow** (`.github/workflows/refresh-datasets.yml`) — runs on the 1st of each month, re-scrapes all four data sources (qualifications, courses, majors, prerequisites), validates, runs the test suite, and opens a pull request with the diff for review.

## [0.6.0] — 2026-04-25

### Added

- **`start_semester` field** (`S1` / `S2` / `SS`) wired end-to-end through `PlanGenerator`, `PlanSearch`, all four `PlannerService` methods, `PlanRequest`, `_execute_plan`, meta output, and the UI. A student starting in S2 2026 now gets a plan that correctly begins `2026 S2 → 2027 S1 → …` instead of always starting at S1.
- **`start_semester` UI selector** — dropdown next to the start year field. Auto-detects the current semester from `new Date()` on page load (April → S1, July → S2, November → SS) without overriding a URL-restored value.
- **Dynamic `start_year` default** — `PlanRequest.start_year` now uses `default_factory=lambda: date.today().year` instead of the hardcoded `2026`. URL state always saves the year so shared links are stable.
- **Double major shared-course banner** — when a double major plan is generated, a new banner below the stats grid lists all courses that count toward both majors (with clickable codes). Each shared course card in the semester grid shows a red `×2` badge.
- **Massey academic calendar labels** — semester headers now show the approximate teaching period ("S1 · Feb – Jun") and a tooltip with enrolment and results dates ("Enrol by late Jan · Results mid Jul"). Dates are clearly marked as approximate.
- **Validation checklist — pool expansion** — failed `CHOOSE_CREDITS` / `CHOOSE_N` requirement nodes now show a collapsible "▸ Pick from N courses" button revealing clickable course codes, so students know exactly what they still need to select.
- **Mobile-optimised course card layout** — `@media (max-width:600px)` now overrides the course card to a 3-column compact grid (code | title/meta | credits) preventing overflow on 390px phones. Modal result rows also collapse the semester column on mobile.
- **`Dockerfile`** — production-ready multi-stage image based on `python:3.12-slim`, non-root `coursemap` user, 2 uvicorn workers on port 8080.
- **`docker-compose.yaml`** — one-command `docker compose up` with health check.
- **`requirements.txt`** — pinned dependencies generated by `pip-compile` for reproducible installs (`pip install -r requirements.txt`).
- **31 new tests** in `tests/test_v06_features.py` covering all of the above.

### Fixed

- **`search.py` was dropping `start_semester`** — `PlanSearch._run_search()` constructed new `PlanGenerator` instances copying all template attributes except `start_semester`, causing S2/SS starts to silently revert to S1. Fixed by adding `start_semester=self.generator_template.start_semester` to the constructor call.
- **URL state suppressed year when `=== 2026`** — the `pushUrl` function skipped saving `start_year` if it equalled 2026, meaning shared links from 2026 would use the wrong year for users visiting in later years. Now always saved.

# Changelog

## [0.4.0] — 2026-04-25

### Added

- **`GET /api/courses/{code}/explain`** — new endpoint that returns a human-readable list of scheduling constraints for any course: which semesters it's offered at the requested campus/mode, how deep its prerequisite chain is, and the earliest possible semester it can be taken.
- **Explain panel in course drawer** — "Explain" button in the course detail sidebar calls the new endpoint and renders a ✓/⚠ constraint list in context of the current plan's campus and mode.
- **SVG prerequisite DAG** — the "Show chain" view in the course drawer now renders a proper directed acyclic graph with curved Bézier edges and arrowheads, colour-coded by course level (green = 100, purple = 200, blue = 300+, red = target course). Each node is clickable to navigate directly to that course's drawer.
- **Rate limiting** (`slowapi`) — plan generation capped at 30 req/min per IP; iCal export at 10 req/min; major search at 200 req/min. Prevents resource exhaustion on a deployed instance.
- **Full credits-per-semester range** — the UI now exposes 15 / 30 / 45 / 60 / 75 / 90 / 120 credit options, matching the full API range (was 15–60 only).
- **Max courses/semester field** — new "Max courses/sem" input in the Options panel wires through to the existing `max_per_semester` API parameter.
- **`prereq_to_dict` / `prereq_to_human`** added to `coursemap.domain.prerequisite` — canonical serialisers for the prerequisite expression tree, accessible to any layer without importing from `api`.
- **35 new tests** in `tests/test_v04_improvements.py` covering: RFC 5545 escaping, the explain endpoint, chain BFS correctness, domain serialisers, iCal/plan consistency, `max_per_semester` wiring, and version assertion.

### Fixed

- **iCal RFC 5545 escaping bug** — `plan_to_ical` previously called `.replace("\n", "\\n")` on a string that already contained literal `\n` sequences from f-string formatting, causing some parsers to reject the output. Fixed by introducing `_escape_ical_text()` which handles the full RFC 5545 TEXT escaping order (backslash first, then `;`, `,`, newline) before folding.
- **`/api/plan/ical` duplication** — the iCal endpoint previously duplicated the entire plan-generation dispatch block (~60 lines). Extracted `_execute_plan(req, svc)` as a shared helper used by both `/api/plan` and `/api/plan/ical`.
- **`_prereq_to_dict` / `_prereq_to_human` duplication** — removed the two private copies in `server.py`; both routes now use the domain-layer functions.
- **BFS in `get_prereq_chain`** — replaced `queue.pop(0)` (O(n)) with `collections.deque` + `popleft()` (O(1)).
- **`_plan_to_out` triple `resolve_major` call** — the function previously called `resolve_major` three times for the same major; now resolved once and reused.
- **API version** bumped from `0.3.0` to `0.4.0` in both `FastAPI()` constructor and `/api` root response.
- **`slowapi` added** to `[project.optional-dependencies] api` and `all` in `pyproject.toml`.

### Changed

- URL state now persists `mps` (max-per-semester) parameter alongside existing parameters, so shared plan links round-trip course-count limits correctly.
