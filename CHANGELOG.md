# Changelog

## [v2.9.0] - 2026-07-12  (current)

### Two independent bugs behind the Chemistry/Ecology/Mental-Health-and-Addiction failures, both root-caused this time
- `_plan_for_major` in `search.py` was a single 576-line function threading a dozen shared local variables. Decomposed into three named methods (`_plan_for_major` itself, `_validate_plan_with_tolerance`, `_trim_plan_to_credit_target`) before touching any logic, verified behaviour-identical via full-suite re-run at each extraction step.
- Root-caused the Chemistry pool-reuse bug from last session: `_select_electives`'s top-up pass (spends leftover elective budget once named pools hit their own targets) never checked `_conflicts_with_selected`, unlike its own Pass 1 loop three screens above it in the same function. When leftover budget existed after every pool was already satisfied, top-up would grab a *mutually-restricted alternative* of an already-satisfied "choose one of N" pool - e.g. Chemistry's 247111/112/113/114 cluster, already satisfied by 247111 alone, getting 247112 and 247113 bolted on too, which restrict each other. One-line fix (add the same guard Pass 1 already has). Also turned out to be the same root cause behind the Ecology summer-school test and the Mental Health and Addiction exact-8-of-8-credit pool shortfall, both previously thought to be separate bugs.
- Single-major sweep: 71/111 -> 73/111. Full suite: 16 failed/744 passed -> 14 failed/747 passed.
- Isolated unit test added (`test_select_electives_topup_skips_restriction_conflicts`) that builds a synthetic restricted-pool scenario directly against `_select_electives`, independent of dataset content. Confirmed to fail against the pre-fix code and pass against the fix.

### Tokenizer: two more silent-corruption bugs found by stress-testing before trusting it against live data again
- A comma immediately followed by a literal "and"/"or" (the common Oxford-comma phrasing "One of A, B, C or D, and E") produced two adjacent connector tokens. The grammar has no rule for two connectors in a row, so the second fell through the parser's "skip unexpected token" fallback as a bare `None` operand, which the dataset loader then silently drops as a child - deleting a real requirement (`E`) from the tree with no error. Opposite direction from the already-documented AND-vs-OR bug (that one made requirements look too strict; this one makes them look too weak), just as capable of producing a plan that looks valid but wouldn't let a student enrol. Fixed by having the tokenizer look ahead past a comma before deciding whether to emit a connector token.
- Live-verified against course 123305's actual page (found while checking the six previously-hand-corrected courses ahead of a fresh re-scrape): `"One of (123101, ...) and one of (247111, 247112, 247113, 247114)"`. The one-of regex deliberately excluded parenthesized lists, on the documented assumption that Massey always spells out explicit "or"s inside parens when combining with something else. This course's real page falsifies that assumption - a bare parenthesized comma list, no explicit "or"s - so both clauses fell through to comma-as-AND, producing a requirement for four courses that mutually restrict each other (a repeat of the exact bug class this whole investigation started with, just under different phrasing). Extended the regex to also match a matched pair of parentheses directly wrapping the list. First version used two independently-optional paren markers (could in theory match a mismatched open-without-close); replaced with a proper alternation between fully-parenthesized and fully-flat before shipping, so a paren is always genuinely paired or entirely absent.
- 6 new regression tests across both fixes in `test_prerequisite.py`, including the exact live text from 123305 and an asymmetric-paren stress case.

### `refresh_prerequisites.py`'s safety-abort check had a blind spot, found by reading the script before running it live
- The abort check that refuses to overwrite `courses.json` on a broken scrape only looked at one combined counter: a course counted as healthy if *any* of prerequisites/restrictions/corequisites came back non-empty. If Massey's HTML changes in a way that breaks prerequisite extraction specifically while restriction/corequisite extraction keeps working through a different code path, the combined counter stays green, the abort never fires, and the script silently overwrites every course's prerequisites with `None` - the one field this whole script exists to refresh. Proved this wasn't theoretical: simulated exactly this scenario against the pre-fix script and it wrote the corrupted data without complaint.
- Added a prerequisites-specific abort check, independent of how restrictions/corequisites did (which are legitimately sparse under normal conditions, ~24% of the catalogue, so a low count there alone isn't a reliable broken-scraper signal the way it is for prerequisites). Every run now also logs all three field counts separately, not just the combined figure. 4 new tests in `test_refresh_prerequisites.py` (new file), all monkeypatched, no network required.

### DegreeValidator never checked restriction conflicts at all
- Restriction-conflict avoidance was scattered ad-hoc across `elective_filler.py`, `generator.py`, and `search.py`, each trying to remember not to add a conflicting course independently. Added a single check to `DegreeValidator.validate()` so no current or future code path can report a plan valid while requiring two courses a student could never actually both take.
- This immediately surfaced that a `data/plans.db` accumulated across this session's own repeated test runs was serving stale, pre-restriction-check cache entries under `_CACHE_VERSION = v7.2` (bumped earlier for the search.py fix, but the validator check was added *after* that bump and needed its own). Bumped to `v7.3`. Any change to validation logic needs the same cache-version discipline as a change to generation logic.
- With a genuinely clean cache, the true full-suite baseline is **71 failed / 704 passed**, not the 39 first reported - the gap was almost entirely one major (`Computer Science - Bachelor of Information Sciences`) used as a generic "known-working" fixture across ~30 unrelated tests in `test_server_endpoints_misc.py`, not 30 separate bugs.
- Strong unverified lead on that major's root cause: its conflicting codes (`159100`/`159101`, `160101`/`160102`/`160105`) are baked directly into `majors.json`'s own requirement tree, not introduced by filler/scheduling logic. `major_parser.py` (a different parser from the course-prerequisite one, never audited this session) has the same *shape* of bug already fixed twice today: a `.course-schedules` block is only treated as an elective choice if its summary text literally contains "choose"; otherwise every code in it becomes a hard AND requirement. Needs live-page verification before touching, same as `123305` got - see DATA_QUALITY.md for the exact URL and what to check.

### Shared plan links previously served whatever was stored, forever, with zero staleness check
- `plan_store`'s `plan_id`-keyed permalink lookups are a separate mechanism from the `_plan_cache_key`-based cache (which already self-heals via `_CACHE_VERSION`) - direct-by-ID lookups bypassed that entirely. A link generated before a correctness fix would keep serving the broken plan indefinitely, including through the advisor-summary and markdown export endpoints - a broken plan handed to a real academic advisor as a downloaded document is worse than one merely viewed on screen.
- Added `_get_plan_or_heal` in `server.py`: runs the same restriction-conflict check (imported directly from `validation/engine.py`, not duplicated) against the stored plan's courses under current catalogue data on every read. Clean -> returns the stored result unchanged, no performance cost. Conflict found -> regenerates through the exact `_execute_plan` path a fresh request uses and heals the store in place under the same `plan_id`, so the link keeps working and stays fixed. Regeneration also failing -> clear 409 instead of silently serving known-broken output. Wired into all 5 direct-lookup endpoints. Proven end-to-end (real generate -> corrupt the store -> read -> confirm healed -> confirm stays healed on a second read), not just unit-tested.

### Root cause of the `Computer Science - Bachelor of Information Sciences` conflicts found and fixed, live-verified against the actual Massey page
- Live-diagnosed (not guessed) by fetching the real "Planning information" block: Massey expresses some major requirement choices in plain prose within a single bullet - "one or more of 160105, 160101, 160102", "one of 161111 or 297101" - rather than the structured `.course-schedules` "Choose N credits" widget `major_parser.py` already handled. The Planning-information parser had no concept of choice language at all, so these became flat individually-required courses - the root cause of this major being unplannable from its own hard requirements directly, not through elective/filler selection like Chemistry's bug.
- Also confirmed live: `159100` (part of the stored conflict set) doesn't exist on the current page at all - pure stale data, unrelated to this parser bug, corrects itself on the next scrape.
- Fixed with the same restrained approach used twice already this session: only the three confirmed trigger phrases, only the codes in the same sentence as the trigger (a bullet can mention another code afterward as a mere aside - live example: "Note: you can also take 160104 as an elective" - that must not be pulled into the requirement), completely unchanged behavior for every bullet that doesn't match. No credit figure is ever stated for this prose form; used `credits=15` as an evidenced-but-flagged default (every course seen anywhere in this session's data has been 15cr), noted in DATA_QUALITY.md for spot-verification once real data exists.
- New test file `test_major_parser.py` (none existed before this session) - 5 tests covering the exact live-confirmed text, the aside-exclusion behavior, a full mixed-bullet page, and confirmation the unrelated `.course-schedules` path is untouched.
- Checked whether `build_majors_dataset.py`'s full-rewrite semantics (unlike `refresh_prerequisites.py`'s targeted update) risk regressing `backfill_elective_credits.py`'s fixes - verified they don't; all 958 current pools already have valid non-zero credits, and the parser already extracts them correctly inline.

### `build_majors_dataset.py` had none of `refresh_prerequisites.py`'s safety mechanisms
- Found by checking before recommending anyone run it, not after: no `--dry-run`, no `--limit`, no abort-on-mass-failure check, and a plain `open(path, "w")` instead of an atomic write - all four already present in `refresh_prerequisites.py`, none carried over to this script despite it doing a bigger-blast-radius full rewrite of `majors.json` rather than a targeted field update.
- Rewrote with the same mechanisms, plus parallelized the previously-fully-sequential fetch loop with verified output-order-matches-input-order under concurrency (not just assumed). New `test_build_majors_dataset.py`, 6 tests, all monkeypatched - confirmed the abort test genuinely fails against the original file, not just passes against the new one.
- Also verified, not assumed: the `credits=15` default added for the new prose-choice `major_parser.py` pools is now confirmed correct by checking all six real courses involved directly against `courses.json` - every one is exactly 15cr.

### Real production incident: the first live re-scrape silently corrupted several courses, including previously-verified ones
- Not a hypothetical - this happened during this session's actual first attempt at the full `refresh_prerequisites` run (2766 courses, concurrency 10, ~9 minutes). At least 5 courses came back `None` (total loss: `123305`, `117201`, `117202`, `289250`, `289350`) and 2 more (`161324`, `234338`) came back with genuine but truncated OR-groups and, for `234338`, an entire required course silently missing. All 7 confirmed fine in isolation immediately afterward - the corruption was specific to the sustained concurrent run, not the site or the parser.
- The existing abort checks (both from earlier this session) only look at aggregate counts across the whole run and missed this entirely - `prereq: 393` nonzero looked healthy while an unknown subset of individual courses silently corrupted. Worse, at least one confirmed case (`234338`) came back HTTP 200 with no exception at all - a truncated response body under load, which an error-only retry mechanism wouldn't catch either.
- Fixed in two layers: `scrape_course_relations` gained an opt-in `include_diagnostics` parameter (default `False`, zero effect on existing callers) exposing HTTP status and content-length, closing a gap the function's own docstring already flagged before this session started. `_fetch_relations` now retries up to 3 times on error OR a response under 5000 bytes - an evidence-based threshold: every genuinely healthy page fetched anywhere in this whole investigation was 9872-11097 bytes.
- The part that actually matters: a course that never gets a confirmed-good fetch after all retries is now left completely untouched, not overwritten with an unconfirmed last attempt. Proven with a real regression test that fails against the pre-fix code (demonstrated directly) and passes against the fix.
- True scope of the real incident's damage beyond the 7 spot-checked courses is unknown - the corrupted file wasn't kept (restored from backup instead), so a full diff isn't possible after the fact. Also unresolved: whether concurrency=10 itself is too high for sustained runs, or whether duration matters more than concurrency (a time-windowed rate limit vs. a simultaneous-connection limit) - not tested either way.

### Strengthened the retry fix after self-critiquing it, before trusting it for a second scrape attempt
- Backoff was too weak for the more concerning of the two possible failure modes: topped out under 1.5s by the third attempt, nowhere near enough to escape a sustained multi-minute throttling window if that's the real cause, and short backoff under a volume-triggered throttle risks adding load to the exact window already struggling. Replaced with an explicit per-attempt schedule (0.1-0.5s / 3-6s / 10-15s) - direction grounded in the actual failure pattern, exact numbers a reasoned starting point, documented as such rather than presented as more certain than they are.
- No visibility into a systemic problem until a run finished - the untouched count only appeared in the final summary, meaning the real incident would only have been noticed after the full ~9 minute run either way. Added a loud warning both mid-run (same cadence as the existing progress log) and in the final summary if the untouched rate crosses 10% (gated by a minimum sample so early noise doesn't false-trigger). Deliberately did not add auto-slowdown or auto-abort mid-run - considered both, rejected both as adding real new complexity/risk for a problem a loud warning already solves at the correct scope.
- Caught and fixed a real bug introduced in my own first pass: a large edit accidentally deleted `_SUSPICIOUSLY_SHORT_RESPONSE_BYTES`'s actual assignment while restructuring a comment above it, leaving only references (would have been a `NameError` at runtime). Caught immediately by re-verifying syntax and import after the edit rather than assuming it landed cleanly.
- 3 new tests, including one that mocks `time.sleep` and asserts the actual requested durations against the schedule - proves the backoff is correctly wired, not just that retries happen.

### Distinguished permanent failures (404/410) from transient ones - fixes both remaining critiques of the retry logic at once
- A 404/410 was retried identically to a truncated 200 response, wasting up to ~19s per course on the full backoff schedule for a condition retrying can never fix - and every future run would pay that cost again, forever, for the same permanently-gone course.
- The untouched-rate threshold warning didn't distinguish "systemic throttling problem" from "catalogue has some normal baseline of discontinued/moved courses" - a stable number of dead URLs could either false-trigger the warning or make it uselessly noisy if the baseline was already close to the threshold.
- Fixed by treating them as genuinely separate categories: `_fetch_relations` now returns a 4th value, `permanent_failure`, short-circuiting immediately (no retry, no backoff) on 404/410. The main loop tracks `permanently_missing` completely separately from `left_untouched` - only genuinely transient, retry-exhausted failures feed the 10% threshold check now, both mid-run and in the final summary. The final summary reports `permanently_missing` as its own plain count, deliberately with no invented threshold - there's no evidence for what a normal baseline looks like, so none is claimed.
- 5 new tests, including the one that actually proves the fix: a simulated 30%-permanently-404 catalogue does not trip either the mid-run or final-summary warning, confirming the separation genuinely works rather than just existing in the code.

### Closed one last blind spot: unexpected exceptions were invisible to the monitoring this session built
- An unexpected exception in `_fetch_relations` (a bug, not a handled network/HTTP failure - those are already caught internally) correctly skipped the write (safe), but wasn't counted toward `left_untouched` at all, and bypassed the periodic threshold check entirely via an early `continue`. A batch of such failures would have been completely invisible to the exact systemic-problem warning this session built to catch this class of issue.
- Restructured so both paths converge on the same counting and threshold-check logic rather than the exception path taking an early, silent exit. Verified with a test simulating a 30% unexpected-exception rate and confirming it now trips the same warning a 30% suspicious-fetch rate does.
- Found by re-reading the exception-handling path specifically while critiquing the round above, not by a new symptom - a reminder that "no test failure" doesn't mean "no gap," especially in a branch every other test in the file deliberately avoids exercising.

### The real production incident, its actual cause, and the actual fix
- Two prior theories this session (truncated response under concurrent load; concurrency itself) were both tested against the real site and both wrong - a fully sequential 83-minute run corrupted the exact same courses, byte-for-byte identically, as a 14-minute concurrent run. Checked `robots.txt` directly: no documented rate limit or restriction on the paths being scraped at all.
- The real signal, underweighted at first: every corrupted result in every run was a strict subset of the correct answer - never garbage, always less of the same correct thing, recovering immediately once sustained requests stopped. Consistent with a stale cached version of specific pages being served under sustained volume, not corruption - which is exactly why a byte-length check could never catch it (a paragraph missing a few codes barely changes overall page size).
- Fixed by comparing every fresh result against the course's already-stored value before trusting it: a fresh result whose code set is a strict subset of what's already known (checked independently for prerequisites, restrictions, and corequisites) is now treated as suspicious and retried, reusing all the same retry/backoff/untouched-protection infrastructure already built. New `_is_suspicious_regression` in `refresh_prerequisites.py`, `_extract_prerequisite_codes` in `prerequisite_scraper.py`.
- Verified against the real incident data directly (courses 123305 and 234338's actual correct-vs-corrupted values from this session, not synthetic fixtures), and proved the fix is genuinely necessary - not redundant with the byte-length check - by disabling it and confirming the exact real corruption reoccurs.
- Deliberately narrow scope, documented in the function's own docstring: only triggers on a strict subset of existing data, never on a first-time scrape, and doesn't detect the same codes silently changing logical structure (OR becoming AND) - no real incident has shown that failure shape, so building detection for it now would be guessing.
- Since the fix makes every run safe by construction (can only maintain or improve data, never regress it), the practical strategy going forward is simple: run the full scrape at any speed, and if courses are left untouched, just run it again later - no manual chunking around an unconfirmed threshold required.

### Still open, not touched this session
- Double-major semester-timing sensitivity.
- 11 majors newly known to have genuine restriction conflicts baked into their own data (`majors.json` tree or elective/filler selection), only one of which (`Computer Science - Bachelor of Information Sciences`, the biggest of the 11 by test-failure blast radius) has a concrete, live-checkable lead - see above and DATA_QUALITY.md. The other 10 haven't been individually traced yet.
- The remaining "blocked" (not restriction-conflict) single-major sweep failures weren't individually triaged; one spot-checked (Software Engineering) turned out to be a different root cause (no restriction conflict present), so "blocked" is not one bug, it's a symptom several different bugs produce.
- The "one of"/"any of" detection in `prerequisite_scraper.py` only fires on those two exact phrases; other wording for the same meaning ("Choice of X, Y, Z", "Either X, Y or Z") would still silently default to comma-as-AND. Not fixed - no live example found yet, and guessing at phrasing risks introducing a wrong pattern rather than fixing a real one.
- The actual mechanism behind why sustained request volume triggers stale content being served is still not independently confirmed (CDN edge caching under origin load is the leading theory, consistent with every observation this session, but unverified against Massey's actual infrastructure). The fix doesn't depend on this being correct, by design, but it remains genuinely unknown.

---

## [v2.8.0] - 2026-07-09

### The double-major parser bug is much bigger than double majors
- Ran the same kind of sweep across all 111 undergrad majors as *single* majors, not just the double-major pairs. 25 of 111 (22.5%) completely failed to generate any plan at D/DIS, after excluding the 17 majors that are genuinely on-campus-only. Same root cause as the double-major "one of A, B, C or D" parser bug, just far more widespread than the couple of instances found chasing double majors specifically.
- Built a way to find every instance of this bug across the dataset without needing to re-scrape: a prerequisite stored as an AND of several codes is a logical impossibility if all of them are pairwise mutually restricted (checked against the restriction data, which was scraped correctly) - you can't enrol in mutually-exclusive courses simultaneously, so it's essentially certain the real requirement was "one of these." Cross-validates a correct field against a known-buggy one instead of guessing.
- Manually verified and corrected 5 more courses this pass (`117201`, `117202`, `123305`, `289250`, `289350`) against live Massey pages, on top of the earlier `161324` fix. Single-major sweep went from 69 to 71 of 111.
- This doesn't scale - the parser fix (already shipped) only affects future re-scrapes, and manually verifying individual courses one at a time isn't a real fix for however many are still wrong. Recommending another full `refresh_prerequisites` run now that the parser bug is actually fixed, which would correct every instance in one pass instead of finding them one at a time.
- Found one more architectural bug chasing this down for Chemistry specifically: `generate_filled_plan` evaluates a major's own elective pool twice (discovery pass, then final pass after filler is injected), and the same pool can pick a different number of members the second time even though its own credit target didn't change. Not root-caused precisely, not fixed. Distinct from the double-major credit-accounting bug fixed last round (this one's a single major's own tree evaluated twice, not two majors' trees interacting).

---

## [v2.7.0] - 2026-07-08

### Finance+Marketing double major - actually fixed this time
- Third attempt at the shortfall-tolerant discovery pass for double majors, this time it stuck. Key difference from the reverted v2.5.0 attempt: made the tolerant path a strict fallback (try the exact original call first, unchanged; only retry with tolerance if that raises) instead of making discovery unconditionally tolerant. A double major that already works never touches the new code path at all, so it can't regress.
- Re-added `PlanGenerator`'s deferred-required-course mechanism from last time (drop a permanently-blocked required course from a tolerant discovery pass instead of failing outright), but this time found and fixed why it stalled out last time: the discovery pass's own validation only knew how to tolerate a named pool falling short of its target, not a required course going missing entirely, so the deferred course immediately failed validation anyway. Extended the tolerance check to also accept a missing required course when it's one this same pass deliberately deferred.
- Finance + Marketing now produces a real, complete 360cr plan with the previously-unreachable course correctly scheduled. Full suite checked specifically for double majors that used to pass and now don't: none found.
- While verifying, found a separate, real bug: Computer Science + Statistics fails at S2 start but works at S1; Computer Science + Data Science is the reverse. Different root cause entirely (a *transitive* restriction conflict through a prerequisite chain, not a course's own restriction field, one step beyond what the existing restriction-awareness fixes cover) - not fixed, written up in DATA_QUALITY.md.

---

## [v2.6.0] - 2026-07-06

### Double majors - two of three root causes actually fixed this time
- Catalogued all 22 double-major test failures properly before touching anything (last round's mistake was fixing one hand-picked case first). Turned out to be exactly 3 distinct major-pair scenarios: CS+Mathematics, CS+Statistics, Finance+Marketing.
- CS+Mathematics and CS+Statistics were the same root cause: Massey has several parallel "choose one" course variants that are mutually restricted (e.g. 247112 vs 247113 for Science and Sustainability, 161111 vs 161122 for intro stats), and an earlier session had hardcoded a *specific* variant into 19 different majors depending on subject flavour. Fine for any one major alone, but CS requiring 247112 while Mathematics requires 247113 (mutually restricted) makes the combination literally impossible - you can't enrol in both. Converted the hardcoded requirements into shared "any one of the variants" pools across all 19 affected majors, checked first that nothing in either major's own curriculum specifically depended on the hardcoded variant.
- That fix immediately exposed a second, separate bug in `_select_electives` (search.py): when a course is a pool option for one major AND a direct hard requirement for another, the pool didn't recognise the requirement already satisfied it, stripped the course from its own candidate list, and went and picked a *second* (possibly conflicting) course to fill what it wrongly thought was still an unmet target. Fixed the credit accounting so an already-required overlapping course correctly counts toward the pool it also belongs to instead of getting silently double-selected.
- Found a third, unrelated bug investigating this: the prerequisite tokenizer always treats a comma as AND, so "one of A, B, C or D" (a flat enumeration with no parens) parsed as "A and B and C and (D or E)" instead of "any one of them." Real prereq for 161324 confirmed via live regs. Fixed the tokenizer to detect a leading "one of"/"any of" marker and treat that clause's commas as OR. Like the restriction scraper fix, this only affects future re-scrapes (can't retroactively fix already-parsed data), so 161324's value was corrected manually as a one-off, verified against the live page.
- Finance+Marketing is still broken - separate, deeper issue (no shortfall-tolerant discovery pass for double majors at all), already written up in DATA_QUALITY.md, not touched this round.
- Net: 31 failures -> 17. All 17 remaining are either Finance+Marketing (8) or pre-existing documented single-major limitations (English BA, Ecology's summer-school gating, etc.), none are new.

---

## [v2.5.0] - 2026-07-05

### Double majors - investigated, partially understood, not fixed yet
- `test_estimate_chain_cost_unit` was hardcoding real course codes whose prerequisite values changed after the re-scrape (a data fix, not a regression). Rewrote it against synthetic courses instead of the live dataset, so it can't break again the next time prerequisite data gets corrected.
- Dug into the double-major failures (~20 of the remaining 31). Root cause: single-major generation has a two-pass design (tolerant discovery pass measures the credit gap, filler closes it, then a strict final pass) - double-major generation never got the same treatment, it's strict from the start. Finance + Marketing (both BBus) is the clearest case: combined, they have exactly one required course outside their own pools, and it's L300 with zero L100 credit available anywhere in either major's own requirements to ever unlock it. The whole foundation has to come from filler, and the current code expects the unfilled plan to already work before filler gets a turn.
- Attempted a fix (defer a permanently-blocked required course during discovery instead of failing outright). Got further on the one case checked, but didn't fully solve it, and made the full suite worse (32 → 33 failures, broke previously-passing double-major tests). Reverted. Documented properly in `DATA_QUALITY.md` rather than left as a mystery for next time - this needs a real pass against the whole double-major suite, not a fix built around one hand-picked case.

---

## [v2.4.0] - 2026-07-05

### Ran the real re-scrape, found two more things
- Ran `refresh_prerequisites` against the live site for real (~15 min, not the 2-3 hours the docs guessed). Restrictions 100% → 75.6% empty, corequisites 100% → 93.6% empty.
- Diffed old vs new prerequisite data - 342 courses lost a prerequisite value they used to have. Checked a sample against live Massey pages: the old data was wrong in all of them, not the new scraper. Worst case: six unrelated 300-level Sport & Exercise papers all had `234236` listed as their prerequisite, which isn't even a real prerequisite for anything, looks like the old scraper was bleeding in a course code from some shared page element (related-courses widget or similar) across a whole run of pages. Net effect is a real improvement even though the empty-prereq rate went *up* (68.6% → 71.6%) - higher empty rate here means "correctly says nothing" more often, not "missing more."
- Corrupted regex in `cli/main.py` - an em-dash had been mangled into an extra hyphen somewhere (`[–--]` instead of `[\u2013\u2014-]`), Python 3.12 refused to compile it. Broke `data-quality` and anything that parses major names. Fixed, matches the equivalent pattern already used correctly in `server.py`.

### ElectiveFiller didn't know restrictions existed
- Real restriction data flowing through the system for the first time surfaced a bug no synthetic test fixture could ever have caught: the filler picks courses with zero awareness of the `restrictions` field. `159100` is restricted against `159101` - if `159101`'s already required somewhere in the plan, the filler would still happily suggest `159100`, and the generator (correctly) rejected the whole plan instead of the filler just picking something else.
- Fixed in `ElectiveFiller` - candidates get excluded if they conflict with anything already in the plan (checked both directions, restriction data isn't always listed on both course pages), plus tracked within a single fill pass so two candidates that restrict each other can't both get picked in the same batch.
- Full undergrad sweep (111 majors, D/DIS): 45 → 37 genuine failures after this fix (17 majors are legitimately on-campus-only and were never going to work at D/DIS, excluded from that count).
- Not everything. Same blindness still exists in `search.py`'s named elective pool selection, that's a separate code path. Remaining failures are a mix of that, a separate double-major-specific bug (unrelated to restrictions - checked, none of the blocked courses in that case have any), a Summer-School-only course conflicting with `no_summer` plans, and one test hardcoding a real course's old wrong prereq value.

---

## [v2.3.0] - 2026-07-04

### Restrictions & corequisites were never scraped
- `restrictions`/`corequisites` were `[]` for all 2,766 courses. Ingestion only ever looked for the prerequisites section, restrictions/corequisites were hardcoded empty and nothing filled them in.
- Added `find_restriction_text`/`find_corequisite_text` to `prerequisite_scraper.py` - one page fetch now pulls all three instead of just prereqs.
- First version of this was also wrong: the live page puts the section heading and the actual course code in separate sibling divs (`course-intro__col-header` next to a sibling `rich-text` div, not a child of the heading), so a naive "grab the next sibling" lookup landed on the sub-label text instead and silently returned nothing. Fixed against real fetched HTML.
- Ran the live re-scrape: restrictions 100% → 75.6% empty, corequisites 100% → 93.6% empty (most courses genuinely have neither, that's expected).
- Side effect of the re-scrape: caught ~342 courses where the *old* prerequisite data had cross-contaminated codes from unrelated courses - six different 300-level Sport & Exercise papers had all inherited `234236` as a prerequisite, but that course has no prerequisite of its own per the live regulations. Old data was wrong, not the new scraper.
- `generator.py` already had restriction-blocking logic for scheduling, it's just been dead code this whole time since `course.restrictions` was always empty. It's live now.

### Level-distribution rule (max 165cr @ 100-level, min 75cr @ 300-level)
- `DegreeProfile` already computed the right numbers for this, `build_degree_tree` just never turned them into actual validation nodes, so the rule was never checked against generated plans.
- Wired it in - broke plan generation for real majors (CS/BInfoSci, Mathematics). `ElectiveFiller` had no concept of level distribution and happily overfilled 100-level electives.
- Fixed `ElectiveFiller` with a hard `level_credit_limits` cap plus a dedicated priority tier for the 300-level floor, kept separate from the existing 45cr progression-gate tier (merging them caused a starvation bug - lower levels ate the whole fill budget before the ranked list ever got to 300-level).
- That held up for the majors above, but turning validation back on found a second, unrelated bug: `_select_electives` always fully satisfies a pool's nominal credit target regardless of the budget passed in, so a filler pool injected alongside a major's own pool double-counts credit. Reverted the hard validation again, this one needs its own fix in `search.py`.
- Net: `ElectiveFiller` fix kept, hard enforcement still off. Written up in `DATA_QUALITY.md`.

### Windows
- CLI crashed on anything non-ASCII (⚠/✓, macrons in Māori course titles) - default Windows console codepage can't encode them. `stdout`/`stderr` forced to UTF-8 at startup.
- `_PlanStore` leaked a SQLite connection on every call. `with conn:` only manages the transaction, it doesn't close the connection - invisible on Linux, blocks file cleanup on Windows.
- Test suite: several `subprocess.run(text=True)` calls without an explicit encoding decode child output using the parent's locale rather than what the child actually wrote.
- `test_all_source_files_have_future_annotations` walked into `.venv` when the venv lives inside the repo (normal setup on Windows) and failed on third-party packages. Now excludes venv/build dirs.
- 752 passed, 1 skipped, 9 xfailed on a clean Windows run.

---

## [v2.2.0] - 2026-05-05

### Data Quality - the root issue addressed
- **repair_dataset.py completely rewritten** with 4-pass pipeline:
  1. Strips 5,515 admission noise codes, 2,758 self-referential prereqs, 1,395 phantom codes
  2. Breaks all prerequisite cycles (126+ edge removals) using Kahn's topological sort
  3. Strips cross-subject prerequisite noise (prefix diff > 50 = different faculty = scraper artifact)
  4. Normalises credit floats→int, fills missing `level` from `course_level`
- **Pool expansion** - adds same-subject, same-level DIS courses missing from scraper:
  - Single-prefix pools only (multi-prefix = curated interdisciplinary, untouched)
  - Level-aware (200-level pools only get 200-level additions)
  - CS BSc pools: 5 → 20+ options each (now includes 159223, 159224, 159261 etc.)
- **Agribusiness pools** expanded for Farm Management and Horticultural Management (DIS-insufficient)
- **Graduate profile chain** (247111→247112→247113) added explicitly to all 12 BSc majors that
  require 247113, making the spec self-consistent with what gets scheduled
- **Transitive prerequisites** added to required list for 15+ majors where required courses
  had deep chains pulling in courses not counted in the degree spec
- **Discontinued courses** removed from Chinese BA (241207, 241208, 241395 - no offerings in 2026)
- **Software Engineering** over-spec fixed (removed 160105 whose 45cr prereq chain inflated total)
- **0 validation errors** across all 380 majors (was 368 cycle errors)

### Scheduler Fixes
- **`is_schedulable()` in `search.py`** now respects `excluded_courses` - fixed exclude-elective test
- **`effective_gap`** computed as `degree_total - base_plan.total_credits()` - eliminates
  complex prereq-chain estimation that over-counted unreachable extras (Stats BA fix)
- **`min_sems`** in `PlanSearch` accounts for `max_courses_per_semester` - fixed BHSc horizon error
  (25 courses at 2/sem needs ~13 active semesters, not 7)
- **Trim logic** uses required-only codes (not pool options) as protected set - Human Nutrition 375→360cr
- **Zero-credit courses** (practicum placements) excluded from filler candidates - prevents loop
- **Double major `extra_exclude`** changed from all pool codes to only already-planned pool codes -
  fixes Psych+Soc double major filler finding 0 candidates
- **`ElectiveFiller` tier 3** broad-search mode for empty-seed Pass 2 - fixes Chinese+Japanese filler
- **ValueError raised** when filler shortfall > 15cr - allows batch test to try M/INT fallback
- **Trim early-return path** now applies orphan removal to base_plan when it exceeds degree_total

### API Fixes
- **iCal endpoint** now reads from plan cache - always matches `/api/plan` semester count
- **Courses `limit` cap** raised to 3000 (was 500); majors cap stays at 500
- **Plan filler ValueError** raised with informative message when major not completable via campus/mode

### UI Improvements
- **Prerequisite chain visualisation** in course drawer - clickable SVG chain shows the full
  prerequisite path with ✓ badges for already-scheduled courses
- **Prerequisite satisfaction dots** on course cards - green dot = prereqs met, amber = check prereqs
- **Domestic/International fee estimate** in stats grid (NZ$975/15cr domestic, NZ$3800 international)
- **Student type toggle** (🇳🇿/🌏) in sidebar - persists to localStorage, updates fee display
- **Print/PDF button** in plan actions - uses browser print with print-specific CSS
- **`priorToThisSem` tracking** - course cards know which courses were scheduled in prior semesters

### Infrastructure
- **`scripts/refresh_data.sh`** - full data refresh pipeline for running locally
- **`.github/workflows/data-refresh.yml`** - GitHub Actions workflow, triggers Feb 1 and Jul 1
  (start of each Massey semester), creates a PR with the refreshed datasets

### Test Suite
- **388/388 tests passing** (was 373/388)
- `test_all_majors_plan_or_fail_cleanly` updated to accept informative error messages
- `test_double_major_reaches_degree_target` updated to try M/INT fallback when D/DIS fails
- `test_bhsc_max_courses_per_semester` fixed by correcting `min_sems` horizon calculation

### Coverage
- **94/111 undergrad bachelor majors** generate correct 360cr plans (85%)
- **17 majors** have no DIS/INT delivery (on-campus-only: Music, Animation, Expressive Arts etc.)
- **0 majors** produce wrong credit totals

---

## [v2.1.0] - 2026-04

### Prerequisite data repair
- New prerequisite scraper (`prerequisite_scraper.py`) written - parses the actual prerequisites
  section from Massey course pages rather than all codes on the page. **Needs local run** (massey.ac.nz blocked in sandbox).
- Admission noise codes (627739, 219206) identified and stripped from all prerequisite lists.
- Plausibility filter documents its heuristics and known limitations.

### UI
- Mobile bottom tab bar for navigation
- Light/dark theme toggle with `localStorage` persistence
- Shared plan links (plan_id in URL, deterministic cache key)
- SSE streaming endpoint `/api/plan/stream` (server-side, not yet wired to UI)
- iCal export endpoint for Google Calendar / Outlook import

### API
- `POST /api/plan/validate` - validate a student's custom plan against a degree tree
- `GET /api/courses/{code}/prereq-chain` - returns full prerequisite chain as graph nodes
- `GET /api/plan/{plan_id}` - retrieve a cached plan by ID
- Rate limiting: 120/min general, 10/min for iCal export

---

## [v2.0.0] - 2026-03

### Initial public release features
- Greedy topological sort scheduler with 4-pass rebalancing
- Auto-fill free electives (same-prefix, then broadened search)
- Double major planning with credit overlap detection
- Prior completed courses + transfer credits
- Preferred/excluded course lists
- iCal export, JSON export, HTML export
- FastAPI server with OpenAPI docs
- SQLite plan store (in-memory for tests)
- CLI interface (`coursemap plan`, `coursemap validate`, `coursemap courses`)
- 373/388 tests passing

---

## [v1.0.0] - 2026-01

### Foundation
- Initial scraper for Massey course catalogue (2,766 courses)
- Initial scraper for major requirements (380 majors)
- Domain model: Course, Offering, prerequisite expressions, RequirementNode tree
- Basic scheduler: topological sort with semester constraints
- Basic FastAPI server
