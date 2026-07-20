# Changelog

## [v2.10.0] - 2026-07-18 (current)

### Scheduler: transitive prerequisite-forced restriction conflicts
- `_select_electives` (`search.py`) only checked a pool candidate's own `restrictions` field, not whether its unavoidable (non-OR) prerequisite chain would force in a course that restricts something already selected. E.g. picking 159261 (bare-requires 159101) after an earlier pool had already picked 159100, which restricts 159101. Added `forced_prereq_closure` / `would_restriction_conflict` (`domain/prerequisite_utils.py`), used by both the pool-selection loop and top-up pass.
- Extended to double majors: hard-required COURSE-node requirements from the *other* major were never visible to pool selection at all (only pool-derived picks and `always_include` were checked). Added an `also_avoid_conflicts_with` parameter threaded from `required_codes` at the call site.
- Consolidated: `elective_filler.py` had its own independent, direct-only restriction check (no closure awareness), a second implementation of the same problem. Both of its check sites now delegate to the shared utility, fixing the same latent bug there.
- Regression test: `test_select_electives_skips_course_whose_forced_prereq_conflicts`, proven against pre-fix code.
- Local suite: 42 failed -> 28 failed, zero regressions (diffed the failing-test set at each stage).

### Test bug: prerequisite-ordering check used the wrong satisfaction semantics
- `test_no_prereq_ordering_violations_in_any_plan` used `PrerequisiteExpression.required_courses()` (a union of all OR branches) to decide what a course needs done first, flagging false positives whenever the *other* OR branch was already satisfied. Rewrote to use `prereqs_met`, matching what the real generator checks, with the plan's own scheduled codes as the known-set (using the full dataset as known produces new false positives on postgrad admission-gatekeeper prerequisites, which are legitimately out of scope for a given plan).

### Scheduler: prior_completed and always_include courses invisible to the conflict check
- Found via real usage, not a test: a student with `completed` courses set got 422s that a fresh plan for the same major didn't. `_would_force_conflict`'s `locked` set (what's actually checked for conflicts) excluded `prior_completed` - it was only in `context` (used for OR-branch "already satisfied" checks). A candidate whose forced prerequisite closure restricted an already-completed course passed the check and only failed later, in full plan validation.
- A second, deeper instance of the same class: a course already locked in via `always_include` (required directly by one major, also a pool option in a double major) can itself carry an unresolved OR prerequisite. `forced_prereq_closure` was only ever computed for the fresh candidate being considered, never for codes already in `locked_codes` - so a candidate conflicting with what an `always_include` course would *itself* eventually resolve to was invisible. Concrete case: 159102 (always_include, OR-requires 159100 or 159101) plus candidate 159261 (bare-requires 159101, which restricts 159100) - fixed CS-BInfSc + Statistics double major.
- `would_restriction_conflict` (`prerequisite_utils.py`) now expands both the candidate's closure and every locked code's own closure before checking, not just the candidate's.
- Regression tests: `test_select_electives_checks_conflicts_against_prior_completed`, `test_select_electives_checks_locked_codes_own_unresolved_prereq`, both proven against pre-fix code.
- Verified in terminal (Windows, PowerShell): 7 of 12 reported failures fixed, remaining 5 confirmed pre-existing and unrelated by cross-checking the exact failure list before and after.


- `Mathematics – Bachelor of Science` directly requires both `160101` and `160102`, but its own 4-candidate L200 pool needs all 4, one of which (`160212`) requires `160105`, which restricts both. Unsatisfiable as scraped, confirmed as a single major with no double-major involved. See DATA_QUALITY.md.
- `Animal Science – Master of Science` directly requires both `119728` and `162760`, which mutually restrict each other. Same shape. Plausibly an AND/OR scraper confusion given the code-prefix mismatch, unverified.
- `English – Bachelor of Arts`'s "blocked" required courses are the already-documented 45cr level-progression gap (previously only named for Chinese BA), not a new issue.

---

## [v2.9.0] - 2026-07-12

### Restriction-conflict avoidance was missing from `_select_electives`'s top-up pass
- The top-up pass (spends leftover elective budget once named pools hit their own targets) never checked for restriction conflicts, unlike the main selection loop earlier in the same function. Once every pool was satisfied, top-up could grab a mutually-restricted alternative of an already-satisfied "choose one of N" pool (e.g. Chemistry's 247111/112/113/114, already satisfied by 247111 alone, getting 247112 and 247113 added too). Root cause behind three previously-separate-looking failures: Chemistry, an Ecology summer-school case, and a Mental Health and Addiction exact-credit pool shortfall.
- `_plan_for_major` (576 lines) split into `_plan_for_major`, `_validate_plan_with_tolerance`, `_trim_plan_to_credit_target`, verified behaviour-identical before any logic changes.
- Single-major sweep: 71/111 -> 73/111. Full suite: 16 failed/744 passed -> 14 failed/747 passed.
- Regression test: `test_select_electives_topup_skips_restriction_conflicts`, synthetic fixture independent of dataset content.

### Tokenizer: two prerequisite-parsing bugs
- A comma directly followed by "and"/"or" ("one of A, B, C or D, and E") produced two adjacent connector tokens; the parser's fallback silently dropped the resulting bare operand, deleting a real requirement from the tree with no error. Fixed by looking ahead past a comma before emitting a connector token.
- The "one of"/"any of" regex excluded parenthesized lists on the assumption Massey always spells out explicit "or"s when combining clauses. Course 123305's live page falsified that ("one of (123101, ...) and one of (247111, ...)", no explicit "or"s), producing a requirement for four mutually-restricting courses. Extended the regex to match a properly paired parenthesized list.
- 6 new tests in `test_prerequisite.py`, including the live 123305 text and an asymmetric-paren case.

### `refresh_prerequisites.py`'s safety-abort check had a blind spot
- The abort check used one combined counter across prerequisites/restrictions/corequisites - a course counted healthy if any field was non-empty. If prerequisite extraction broke while restriction/corequisite extraction kept working through a different code path, the combined counter stayed green and the script would overwrite every course's prerequisites with `None`. Added a prerequisites-specific abort check (restrictions/corequisites are legitimately sparse under normal conditions, ~24% of the catalogue, so a low count there isn't a reliable broken-scraper signal). All three field counts now logged separately. 4 new tests in `test_refresh_prerequisites.py`.

### `DegreeValidator` never checked restriction conflicts
- Restriction-conflict avoidance was scattered ad hoc across `elective_filler.py`, `generator.py`, and `search.py`. Added a single check to `DegreeValidator.validate()` as the authoritative backstop.
- Surfaced a stale `data/plans.db` cache serving pre-restriction-check entries under an outdated `_CACHE_VERSION`; bumped to `v7.3`.
- True full-suite baseline after a clean cache: 71 failed / 704 passed, not the previously-reported 39 - almost entirely one major (`Computer Science – Bachelor of Information Sciences`) used as a fixture across ~30 tests in `test_server_endpoints_misc.py`, not 30 separate bugs.

### Shared plan links served stale plans indefinitely
- `plan_store`'s `plan_id`-keyed lookups bypassed the `_plan_cache_key`-based cache's self-healing entirely - a link generated before a correctness fix kept serving the broken plan forever, including through advisor-summary and markdown export. Added `_get_plan_or_heal` in `server.py`: re-checks restriction conflicts on every read against current catalogue data, regenerates and heals the store in place if broken, returns 409 if regeneration also fails. Wired into all 5 direct-lookup endpoints.

### `Computer Science – Bachelor of Information Sciences` conflicts root-caused
- Live-verified against Massey's Planning Information block: some major requirement choices are expressed as plain prose within a bullet ("one or more of 160105, 160101, 160102", "one of 161111 or 297101") rather than the structured "Choose N credits" widget `major_parser.py` already handled, so they parsed as flat AND requirements. Fixed for the confirmed trigger phrases only, scoped to codes in the same sentence as the trigger. No credit figure is given for this prose form; `credits=15` used as an evidenced default (every course checked this pass was 15cr), flagged in DATA_QUALITY.md for spot-verification.
- Also confirmed live: `159100` (part of the stored conflict) doesn't exist on the current page at all - stale data, corrects on next scrape.
- New `test_major_parser.py`, 5 tests.

### `build_majors_dataset.py` had none of `refresh_prerequisites.py`'s safety mechanisms
- No `--dry-run`, no `--limit`, no abort-on-mass-failure, plain `open(path, "w")` instead of atomic write. Added all four, parallelized the previously sequential fetch loop with output order verified to match input order under concurrency. New `test_build_majors_dataset.py`, 6 tests.

### Production incident: live re-scrape corrupted several courses, including previously-verified ones
- A full `refresh_prerequisites` run (2766 courses, concurrency 10, ~9 min) returned `None` for at least 5 courses (`123305`, `117201`, `117202`, `289250`, `289350`) and truncated OR-groups for 2 more (`161324`, `234338`, the latter also missing an entire required course). All 7 confirmed fine when checked in isolation - corruption was specific to the sustained run.
- Existing abort checks only looked at aggregate counts and missed individual-course corruption; at least one case (`234338`) returned HTTP 200 with no exception, a truncated body under load.
- `scrape_course_relations` gained an opt-in `include_diagnostics` parameter exposing HTTP status and content length. `_fetch_relations` retries up to 3 times on error or a response under 5000 bytes (every genuinely healthy page observed was 9872-11097 bytes). A course that never gets a confirmed-good fetch after retries is left untouched, not overwritten with an unconfirmed attempt.
- Retry backoff extended to an explicit per-attempt schedule (0.1-0.5s / 3-6s / 10-15s), long enough to plausibly clear a sustained throttling window.
- Added a loud warning, both mid-run and in the final summary, if the untouched rate crosses 10%. 3 new tests, including one asserting the actual requested backoff durations.
- 404/410 short-circuits immediately with no retry (retrying can't fix a resource that's gone). `permanently_missing` tracked separately from `left_untouched` so a catalogue's normal baseline of discontinued courses doesn't trip the systemic-throttling warning. 5 new tests.
- An unexpected exception in `_fetch_relations` (a bug, not a handled network/HTTP failure) correctly skipped the write but wasn't counted toward `left_untouched` and bypassed the threshold check via an early `continue`. Restructured so both paths converge on the same counting logic.
- Root cause: two theories (truncated response under concurrent load; concurrency itself) were both tested against the live site and both wrong - a fully sequential 83-minute run corrupted the exact same courses, byte-for-byte, as a 14-minute concurrent run. `robots.txt` has no documented rate limit on the scraped paths. Every corrupted result in every run was a strict subset of the correct answer, consistent with a stale cached version of specific pages being served under sustained volume (a currency problem, not truncation) - which a byte-length check could never catch.
- Fixed by comparing every fresh result against the course's already-stored value: a fresh result whose code set is a strict subset of what's already known (checked independently for prerequisites, restrictions, corequisites) is treated as suspicious and retried through the existing retry infrastructure. New `_is_suspicious_regression` in `refresh_prerequisites.py`. Verified against the real incident data (123305, 234338) and confirmed necessary by disabling it and reproducing the corruption. Scope is deliberately narrow: only strict-subset regressions, never a first scrape, doesn't detect the same codes changing logical structure (OR becoming AND).
- Makes every run safe by construction (can only maintain or improve stored data, never regress it); if courses are left untouched, re-running later is sufficient.

### Still open
- Double-major semester-timing sensitivity.
- 11 majors known to have restriction conflicts baked into their own data; only `Computer Science – Bachelor of Information Sciences` has a concrete lead (see above). The other 10 not individually traced.
- Single-major sweep "blocked" failures beyond restriction conflicts not individually triaged - at least one spot-checked case (Software Engineering) has a different root cause.
- "One of"/"any of" detection in `prerequisite_scraper.py` only fires on those two exact phrases; other phrasing ("Choice of X, Y, Z", "Either X, Y or Z") still defaults to comma-as-AND.
- Mechanism behind stale content under sustained request volume unconfirmed (CDN edge caching under origin load is the leading theory). The regression-detection fix doesn't depend on this being correct.

---

## [v2.8.0] - 2026-07-09

### Double-major parser bug is broader than double majors
- Swept all 111 undergrad majors as single majors, not just double-major pairs: 25 of 111 (22.5%) failed to generate any plan at D/DIS, excluding 17 genuinely on-campus-only majors. Same root cause as the double-major "one of A, B, C or D" parser bug.
- Cross-validated: a prerequisite stored as an AND of several codes that are all pairwise mutually restricted is a logical impossibility, since a student can't enrol in mutually-exclusive courses simultaneously - near-certain evidence the real requirement was "one of these." Found and manually corrected 5 more courses this way (`117201`, `117202`, `123305`, `289250`, `289350`) against live Massey pages, on top of the earlier `161324` fix. Single-major sweep: 69 -> 71 of 111.
- Manual per-course correction doesn't scale; a full `refresh_prerequisites` re-scrape (now that the tokenizer fix is shipped) would correct every instance in one pass.
- `generate_filled_plan` evaluates a major's own elective pool twice (discovery pass, then final pass after filler injection) and can pick a different number of pool members the second time despite an unchanged credit target - found while chasing Chemistry, not root-caused, not fixed.

---

## [v2.7.0] - 2026-07-08

### Finance+Marketing double major fixed
- Shortfall-tolerant discovery pass for double majors, made a strict fallback (unchanged original call tried first; tolerant retry only on failure), so working double majors can't regress through the new path.
- Re-added `PlanGenerator`'s deferred-required-course mechanism (drop a permanently-blocked required course from a tolerant discovery pass instead of failing outright); extended the discovery pass's validation tolerance to also accept a missing required course when it's one this pass deliberately deferred, which is why the mechanism stalled previously.
- Finance + Marketing now produces a complete 360cr plan.
- Found separately: Computer Science + Statistics fails at S2 start but works at S1; Computer Science + Data Science is the reverse. Root cause is a transitive restriction conflict through a prerequisite chain, one step beyond the existing restriction-awareness checks. Not fixed, written up in DATA_QUALITY.md.

---

## [v2.6.0] - 2026-07-06

### Double majors: two of three root causes fixed
- Catalogued all 22 double-major test failures: exactly 3 distinct major-pair scenarios (CS+Mathematics, CS+Statistics, Finance+Marketing).
- CS+Mathematics and CS+Statistics: Massey has several parallel mutually-restricted "choose one" course variants (e.g. 247112 vs 247113, 161111 vs 161122); a specific variant had been hardcoded per-major across 19 majors, so combinations needing different hardcoded variants were structurally impossible. Converted the hardcoded requirements into shared "any one of the variants" pools across all 19 affected majors.
- That fix exposed a second bug in `_select_electives`: when a course is both a pool option for one major and a direct hard requirement for another, the pool didn't recognise the requirement as already satisfying it, dropped the course from its candidate list, and picked a second (possibly conflicting) course to fill what it wrongly thought was still an unmet target. Fixed the credit accounting so an already-required overlapping course counts toward the pool it also belongs to.
- Found a third, unrelated bug: the prerequisite tokenizer always treats a comma as AND, so "one of A, B, C or D" (flat enumeration, no parens) parsed as an AND/OR mix instead of a full OR. Fixed the tokenizer to detect a leading "one of"/"any of" marker and treat that clause's commas as OR. Course 161324 corrected manually and verified against the live page (data fixes don't retroactively apply to already-parsed data).
- Finance+Marketing left broken (separate cause: no shortfall-tolerant discovery pass for double majors at all), written up in DATA_QUALITY.md.
- Net: 31 failures -> 17. All 17 remaining are Finance+Marketing (8) or pre-existing documented single-major limitations (English BA, Ecology summer-school gating).

---

## [v2.5.0] - 2026-07-05

### Double majors: investigated, not fixed
- `test_estimate_chain_cost_unit` hardcoded real course codes whose prerequisite values changed after a data correction. Rewritten against synthetic courses so it can't break on future data fixes.
- Root cause of ~20 of the remaining 31 double-major failures: single-major generation has a two-pass design (tolerant discovery pass measures the credit gap, filler closes it, strict final pass); double-major generation is strict from the start. Finance + Marketing has exactly one required course outside either major's own pools, L300 with zero L100 credit available anywhere in either major's own requirements to unlock it.
- Attempted fix (defer a permanently-blocked required course during discovery) made the full suite worse (32 -> 33 failures, broke previously-passing double-major tests). Reverted, documented in DATA_QUALITY.md.

---

## [v2.4.0] - 2026-07-05

### Live re-scrape
- Ran `refresh_prerequisites` against the live site (~15 min). Restrictions 100% -> 75.6% empty, corequisites 100% -> 93.6% empty.
- Diffed old vs new prerequisite data: 342 courses lost a prerequisite value they previously had. Sample-checked against live Massey pages: old data was wrong in all of them. Worst case: six unrelated 300-level Sport & Exercise papers had all inherited `234236` as a prerequisite, not a real requirement for any of them - old scraper was bleeding in a course code from a shared page element across a run of pages. Empty-prereq rate rising (68.6% -> 71.6%) is a net improvement here, since it means "correctly says nothing" more often.
- `cli/main.py` had a corrupted em-dash regex (`[–--]` instead of `[\u2013\u2014-]`) that Python 3.12 refused to compile, breaking `data-quality` and major-name parsing. Fixed to match the equivalent pattern already correct in `server.py`.

### ElectiveFiller had no restriction awareness
- Real restriction data flowing through the system for the first time surfaced that the filler picked courses with zero awareness of the `restrictions` field (`159100` restricted against `159101` could still get suggested if `159101` was already required elsewhere, and the generator correctly rejected the whole plan afterward). Candidates now excluded if they conflict with anything already in the plan (checked both directions), plus tracked within a single fill pass so two conflicting candidates can't both get picked in the same batch.
- Full undergrad sweep (111 majors, D/DIS): 45 -> 37 genuine failures (17 legitimately on-campus-only majors excluded from the count).
- Same blindness still present in `search.py`'s named elective pool selection (separate code path, not fixed this pass). Remaining failures also include a Summer-School-only course conflicting with `no_summer` plans, and one test hardcoding a real course's old, now-wrong prerequisite value.

---

## [v2.3.0] - 2026-07-04

### Restrictions & corequisites were never scraped
- `restrictions`/`corequisites` were `[]` for all 2,766 courses; ingestion only ever looked for the prerequisites section. Added `find_restriction_text`/`find_corequisite_text` to `prerequisite_scraper.py` so one page fetch pulls all three fields.
- First version's sibling-lookup was wrong (the live page puts the section heading and the course code in separate sibling divs, not parent/child), landing on sub-label text instead. Fixed against real fetched HTML.
- Re-scrape: restrictions 100% -> 75.6% empty, corequisites 100% -> 93.6% empty (most courses genuinely have neither).
- Side effect: caught ~342 courses where old prerequisite data had cross-contaminated codes from unrelated courses (six 300-level Sport & Exercise papers had all inherited `234236`, which has no prerequisite of its own per the live regulations).
- `generator.py` already had restriction-blocking scheduling logic; it had been dead code the whole time since `course.restrictions` was always empty.

### Level-distribution rule (max 165cr @ 100-level, min 75cr @ 300-level)
- `DegreeProfile` already computed the right numbers; `build_degree_tree` never turned them into validation nodes, so the rule was never checked against generated plans.
- Wiring it in broke real majors (CS/BInfoSci, Mathematics) - `ElectiveFiller` had no concept of level distribution and overfilled 100-level electives. Fixed with a hard `level_credit_limits` cap plus a dedicated priority tier for the 300-level floor, kept separate from the existing 45cr progression-gate tier (merging the two tiers caused a starvation bug where lower levels consumed the whole fill budget first).
- That held, but turning validation back on found a second bug: `_select_electives` always fully satisfies a pool's nominal credit target regardless of the budget passed in, so an injected filler pool alongside a major's own pool double-counts credit. Reverted hard validation again pending a `search.py` fix. Written up in DATA_QUALITY.md.

### Windows
- CLI crashed on non-ASCII output (⚠/✓, macrons in Māori course titles) under the default Windows console codepage. `stdout`/`stderr` forced to UTF-8 at startup.
- `_PlanStore` leaked a SQLite connection per call (`with conn:` manages the transaction, not the connection) - invisible on Linux, blocks file cleanup on Windows.
- Several `subprocess.run(text=True)` calls without explicit encoding decoded child output using the parent locale.
- `test_all_source_files_have_future_annotations` walked into `.venv` on a Windows in-repo venv and failed on third-party packages; now excludes venv/build dirs.
- 752 passed, 1 skipped, 9 xfailed on a clean Windows run.

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
- `.github/workflows/data-refresh.yml`, triggered Feb 1 and Jul 1, opens a PR with refreshed datasets.

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
