# Changelog

## [Unreleased]

### Added
- `credits_override` (`/api/plan`, `--credits-override` CLI flag) and `GET /api/majors/pathway-notice`, for qualifications with a documented alternate credit total (currently MSc's 180cr/240cr split). Single-major only.
- Split `ui.html` (3,852 lines) into a 450-line page shell plus `static/app.css` and `static/app.js`, served via `/static`.
- JS test suite (vitest + jsdom) for `app.js` - previously untested. Covers `extractMinorCodes`, `getSaved`/`setSaved`, `_reqFromUrl`.

### Fixed
- False-positive "Free electives" warning on every non-auto-filled single-major plan (`degree_tree_for_major` always validated with `keep_open_pools=True`). Kept for double majors, where it's genuinely informative.
- Fee confidence/exclusions were computed server-side but never shown in the UI. `renderPlan` now fetches `/api/plan/fees`.
- Double-major plans skipped structural validation entirely in both the API and CLI. Both now validate each major's tree independently.
- `Education – MA`'s `267860` prerequisite: mis-scraped AND of 5 options, corrected to the real OR.
- 6 correlated Part One/Part Two majors (Earth Science, OHS, Māori Health, Geography, Sociology, Ecology and Conservation MSc) were storing both pathway halves as simultaneous requirements instead of a choice. Re-encoded with `ANY_OF(ALL_OF(...), ALL_OF(...))` - the engine already supported this shape, the data didn't use it.
- `Chinese – BA` prerequisite deadlock: `241304`/`241305` require `241301`+`241302`, but `241301` restricts `241302`. A real Massey pattern (restriction ≠ enrolment block) the planner can't express yet. Not fixed.
- `_trim_plan_to_credit_target` could strip a course from an already-satisfied pool to fix an overshoot elsewhere. Now pool-aware. Fixed 2 Master of Finance majors plus 7 more previously blamed on the level-progression rule.
- 30 of 32 verified qualification-length fixes were never actually written to `datasets/qualifications.json` - only baked in for the runtime function, not the shipped file. All 32 now applied directly.
- Financial Analytics MFin's 3-pool elective failure: overlapping candidate lists across pools weren't cross-counted.
- `PMART`/`PMSCN` stored at 240cr, actually 180cr each.
- `_elective_sort_key` had no credit-fit awareness, preferring fragmented picks over an exact single-course match. Fixed Geography, English, Sociology MA.
- Part 1/2 pairing only matched Roman-numeral titles; every real course uses Arabic digits, so it never fired. Switched to code-adjacency matching.

### Investigated, not fixed
- `HRM MBS`, `Economics MA`: over-specified required lists (same category as the ~36-major group in DATA_QUALITY.md).
- `TESOL MAppLing`: correlated-pathway duplication plus a separate over-specification.
- `Education MA` Part Two: real codes identified, not shipped - constructing the coursework pathway as described still overshoots by 15cr for an unresolved reason. `xfail`'d rather than guessed at.
- 56 of 80 majors with 3+ elective pools now pass after the trim fix; remaining 13 are the known over-specified-list category.

### Process
- A "fixed and tested" qualification-length correction wasn't affecting runtime output because it had only ever been verified in isolation, never against the shipped file. Verifying a data fix now means loading the real file from disk.
- `scripts/run_all_data_refresh.py` had no `--help` - it silently started a 35-45 min scrape. Added a guard.

---

## [v2.10.0] - 2026-07-18

- Scheduler didn't check whether a candidate's own unavoidable prerequisite chain would force in a course that restricts something already picked. Added `forced_prereq_closure`/`would_restriction_conflict`, used by both single- and double-major selection and consolidated into `elective_filler.py`'s separate, weaker version of the same check.
- Same gap existed for `prior_completed` and `always_include` courses - a locked-in course's own unresolved prerequisite wasn't checked against new picks. Fixed CS-BInfSc + Statistics double major.
- `test_no_prereq_ordering_violations_in_any_plan` used the wrong satisfaction semantics (union of OR branches instead of what's actually scheduled), causing false positives.
- Scraper request failures (timeout, DNS, connection error) were only logged at `debug` level, indistinguishable from a genuinely short real response. Now surfaces the actual exception.
- `Mathematics BSc`, `Animal Science MSc`: directly require two mutually-restricted courses, unsatisfiable as scraped. Not fixed, see DATA_QUALITY.md.

---

## [v2.9.0] - 2026-07-12

- `_select_electives`'s top-up pass (spends leftover budget after named pools hit their targets) never checked restriction conflicts, unlike the main selection loop - could grab a mutually-restricted alternative of an already-satisfied pool. Root cause behind 3 separate-looking failures (Chemistry, an Ecology summer-school case, Mental Health and Addiction).
- Prerequisite tokenizer: a comma directly followed by "and"/"or" silently dropped the next operand from the tree; the "one of"/"any of" regex excluded parenthesized lists, missing a real case on course 123305's live page.
- `refresh_prerequisites.py`'s safety-abort check used one combined counter across all three fields - if prerequisite extraction broke while restrictions/corequisites kept working, it stayed green and would have overwritten every course's prerequisites with `None`. Split into a prerequisites-specific check.
- `DegreeValidator` never actually checked restriction conflicts - the check existed but was scattered ad hoc across 3 other files. Added as a single authoritative check on `validate()`.
- Shared plan links served stale plans indefinitely, including through a correctness fix - `plan_id` lookups bypassed the cache's self-healing entirely. Added `_get_plan_or_heal`, wired into all 5 direct-lookup endpoints.
- `CS-BInfSc` restriction conflicts root-caused: some Massey requirement choices are written as plain prose in a bullet, not the structured widget the parser already handled - fixed for the confirmed trigger phrases.
- `build_majors_dataset.py` had none of `refresh_prerequisites.py`'s safety mechanisms (no `--dry-run`, no abort-on-mass-failure, non-atomic write). Added all four.
- A live re-scrape corrupted several already-correct courses under sustained request volume - not truncation, evidence points to stale cached pages being served. Added `_is_suspicious_regression`: a fresh result that's a strict subset of the already-stored value is retried instead of accepted, making every run safe by construction.
- Still open: double-major semester-timing sensitivity; 11 majors with restriction conflicts baked into their own data (only 1 root-caused); "one of"/"any of" detection only fires on those two exact phrases.

---

## [v2.8.0] - 2026-07-09

- Swept all 111 undergrad majors as single majors: 25 of 111 failed to generate any plan at D/DIS, same root cause as a double-major parser bug. A prerequisite stored as an AND of pairwise-mutually-restricted codes is a logical impossibility - used that to find and manually correct 5 more mis-scraped courses against live pages.
- `generate_filled_plan` evaluates a major's own elective pool twice (discovery, then final) and can pick a different count the second time despite an unchanged target - found while chasing a Chemistry failure, not root-caused.

---

## [v2.7.0] - 2026-07-08

- Added a shortfall-tolerant discovery pass for double majors (single-major generation already had one), with the original strict call tried first so working double majors can't regress. Fixed Finance + Marketing.
- Found separately: Computer Science + Statistics fails at S2 start but works at S1, and the reverse for Data Science - a transitive restriction conflict through a prerequisite chain. Not fixed, see DATA_QUALITY.md.

---

## [v2.6.0] - 2026-07-06

- Catalogued all double-major failures down to 3 distinct major-pair scenarios. Massey has several parallel mutually-restricted "choose one" course variants; a specific variant had been hardcoded per-major across 19 majors, making some combinations structurally impossible. Converted to shared "any variant" pools.
- That exposed a credit-accounting bug: a course that's both a pool option for one major and a hard requirement for another wasn't recognised as already satisfying the pool, so a second, possibly-conflicting course got picked unnecessarily.
- Tokenizer always treated a comma as AND, so "one of A, B, C or D" parsed as a mix instead of a full OR. Fixed; failures dropped from 31 to 17.

---

## [v2.5.0] - 2026-07-05

- Root cause of ~20 remaining double-major failures: single-major generation has a tolerant discovery pass + filler + strict final pass; double-major generation was strict from the start.
- Attempted fix (defer a permanently-blocked required course during discovery) made the suite worse and broke passing tests. Reverted.

---

## [v2.4.0] - 2026-07-05

- Live re-scrape: 342 courses lost a stale prerequisite they shouldn't have had (e.g. 6 unrelated Sport & Exercise papers had all inherited an unrelated course code from a shared page element).
- `ElectiveFiller` had zero restriction awareness - could suggest a course that conflicts with one already required elsewhere, only caught later when the generator rejected the whole plan. Fixed; failures dropped from 45 to 37 across 111 majors.
- `cli/main.py` had a corrupted em-dash regex that Python 3.12 refused to compile, breaking major-name parsing.

---

## [v2.3.0] - 2026-07-04

- `restrictions`/`corequisites` were empty for all 2,766 courses - ingestion only ever looked for the prerequisites section. Added extraction for all three fields in one page fetch. Caught ~342 more cross-contaminated prerequisite codes as a side effect.
- `generator.py` already had restriction-blocking logic; it had been dead code the whole time since the field was always empty.
- Wired in the max-165cr-at-100-level / min-75cr-at-300-level rule; broke real majors until `ElectiveFiller` got a level-distribution cap. A second bug (pool credit double-counting) meant hard enforcement had to be reverted again - see DATA_QUALITY.md.
- Windows: CLI crashed on non-ASCII output under the default console codepage; a SQLite connection leaked per call; subprocess output decoded with the wrong encoding. All fixed.

---

## [v2.2.0] - 2026-05-05

### Data quality
- `repair_dataset.py` rewritten as a 4-pass pipeline: strips 5,515 admission-noise codes, 2,758 self-referential prerequisites, 1,395 phantom codes; breaks all prerequisite cycles (126+ edge removals, Kahn's topological sort); strips cross-subject prerequisite noise (prefix difference > 50 treated as a scraper artifact); normalises credit floats to int, fills missing `level` from `course_level`.
- Pool expansion adds same-subject, same-level DIS courses missing from the scraper (single-prefix pools only, level-aware). CS BSc pools: 5 -> 20+ options each.
- Agribusiness pools expanded for Farm Management and Horticultural Management (DIS-insufficient).
- Graduate-profile chain (247111 -> 247112 -> 247113) added explicitly to all 12 BSc majors that require 247113.
- Transitive prerequisites added to the required list for 15+ majors where required courses had deep chains pulling in uncounted courses.
- Discontinued courses removed from Chinese BA (241207, 241208, 241395 - no 2026 offerings).
- Software Engineering over-specification fixed (removed 160105, whose 45cr prerequisite chain inflated the total).
- 0 validation errors across all 380 majors (previously 368 cycle errors).

### Scheduler fixes
- `is_schedulable()` in `search.py` now respects `excluded_courses`.
- `effective_gap` computed as `degree_total - base_plan.total_credits()`, replacing a prereq-chain estimation that over-counted unreachable extras.
- `min_sems` in `PlanSearch` accounts for `max_courses_per_semester` (BHSc: 25 courses at 2/sem needs ~13 active semesters, not 7).
- Trim logic uses required-only codes as the protected set, not pool options (Human Nutrition 375 -> 360cr).
- Zero-credit courses (practicum placements) excluded from filler candidates.
- Double major `extra_exclude` changed from all pool codes to only already-planned pool codes (fixes Psych+Soc double major filler finding 0 candidates).
- `ElectiveFiller` tier 3 broad-search mode for empty-seed Pass 2 (fixes Chinese+Japanese filler).
- `ValueError` raised when filler shortfall exceeds 15cr, allowing the batch test to try M/INT fallback.
- Trim early-return path now applies orphan removal to base_plan when it exceeds degree_total.

### API fixes
- iCal endpoint reads from the plan cache, keeping semester count in sync with `/api/plan`.
- Courses `limit` cap raised to 3000 (majors cap stays at 500).
- Plan-filler `ValueError` includes an informative message when a major isn't completable via the given campus/mode.

### UI improvements
- Prerequisite chain visualisation in the course drawer (clickable SVG, ✓ badges for already-scheduled courses).
- Prerequisite satisfaction dots on course cards.
- Domestic/international fee estimate in the stats grid (NZ$975/15cr domestic, NZ$3800 international).
- Student-type toggle in the sidebar, persisted to localStorage.
- Print/PDF button using browser print with print-specific CSS.
- `priorToThisSem` tracking on course cards.

### Infrastructure
- `scripts/refresh_data.sh` for a full local data refresh.

### Test suite
- 388/388 passing (previously 373/388).
- `test_all_majors_plan_or_fail_cleanly` updated to accept informative error messages.
- `test_double_major_reaches_degree_target` updated to try M/INT fallback when D/DIS fails.
- `test_bhsc_max_courses_per_semester` fixed by correcting the `min_sems` horizon calculation.

### Coverage
- 94/111 undergrad bachelor majors generate correct 360cr plans (85%).
- 17 majors have no DIS/INT delivery (on-campus-only: Music, Animation, Expressive Arts, etc.).
- 0 majors produce wrong credit totals.

---

## [v2.1.0] - 2026-04

### Prerequisite data repair
- New prerequisite scraper (`prerequisite_scraper.py`) parses the actual prerequisites section from Massey course pages rather than all codes on the page.
- Admission-noise codes (627739, 219206) identified and stripped from all prerequisite lists.
- Plausibility filter documents its heuristics and known limitations.

### UI
- Mobile bottom tab bar for navigation.
- Light/dark theme toggle with localStorage persistence.
- Shared plan links (plan_id in URL, deterministic cache key).
- SSE streaming endpoint `/api/plan/stream` (server-side, not yet wired to UI).
- iCal export endpoint for Google Calendar / Outlook import.

### API
- `POST /api/plan/validate` - validate a student's custom plan against a degree tree.
- `GET /api/courses/{code}/prereq-chain` - full prerequisite chain as graph nodes.
- `GET /api/plan/{plan_id}` - retrieve a cached plan by ID.
- Rate limiting: 120/min general, 10/min for iCal export.

---

## [v2.0.0] - 2026-03

### Initial public release
- Greedy topological sort scheduler with 4-pass rebalancing.
- Auto-fill free electives (same-prefix, then broadened search).
- Double major planning with credit overlap detection.
- Prior completed courses + transfer credits.
- Preferred/excluded course lists.
- iCal export, JSON export, HTML export.
- FastAPI server with OpenAPI docs.
- SQLite plan store (in-memory for tests).
- CLI interface (`coursemap plan`, `coursemap validate`, `coursemap courses`).
- 373/388 tests passing.

---

## [v1.0.0] - 2026-01

### Foundation
- Initial scraper for the Massey course catalogue (2,766 courses).
- Initial scraper for major requirements (380 majors).
- Domain model: Course, Offering, prerequisite expressions, RequirementNode tree.
- Basic scheduler: topological sort with semester constraints.
- Basic FastAPI server.
