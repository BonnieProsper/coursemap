# Changelog

## [Unreleased]

### Fixed: qualification-length corrections now ship in the dataset
- Thirty qualification-length corrections existed in `_VERIFIED_QUALIFICATION_LENGTH_FIXES` but had not been persisted to `datasets/qualifications.json`. Only PMART and PMSCN had actually landed in the shipped dataset.
- Applied all 32 verified length corrections to `datasets/qualifications.json` and verified the saved file directly against the repair table.
- Confirmed the runtime impact on Financial Analytics and Research - Master of Finance: `free_elective_gap()` now returns 0 instead of 60, and the generated plan targets the real 180cr total instead of 240cr-derived arithmetic.
- Full suite remained at the known baseline: 4 failed / 839 passed / 2 skipped / 13 xfailed.

### Investigated: Financial Analytics/Research and Financial Technology - Master of Finance elective-pool starvation
- After the qualification-length fix above, Financial Analytics and Research - Master of Finance still fails `DegreeValidator`: `"Elective pool: have 0cr, need 60cr from 11 available courses."`
- Confirmed this is not the level-progression limitation (all of this major's pools are flat 700/800-level, no level-progression gate applies) and not the Part One/Two correlated-pathway gap (its pools aren't correlated-range shaped, just overlapping-candidate-list shaped).
- Traced to `generate_best_plan`: it only ever draws from the first two of this major's three named elective pools (135cr from 6 courses - more than the 120cr those two pools actually need, since their candidate lists overlap and the selection doesn't recognise that a course counted toward one pool's target also counts toward the other's), then stops. The third pool (60cr, 11 fully-schedulable candidates) never gets touched; `generate_filled_plan`'s generic top-up filler has no concept of a specific unmet named pool, only a total credit gap, so it pads the remainder with unrelated low-level courses instead.
- Confirmed not inherent to the pool shape: Risk Analytics - Master of Finance, same qualification, same three-overlapping-pool structure with a different credit split (45/75/60 instead of 30/90/60), schedules correctly today. The regression test uses it as a passing control.
- Scanned all 80 majors with 3+ named elective pools: 45 `DegreeValidator` failures total, but most are the already-`xfail`'d level-progression limitation or Part One/Two gap, confirmed by checking a sample directly (not assumed). **At least 16 are Master's-level majors with no level-progression gate at all** - the real, currently-unscoped size of this specific bug - each needing the same individual verification done for Finance here before assuming they share this cause.
- Not fixed: the bug is in `search.py`'s pool-selection order or greedy-selection logic. Documented via `test_finance_multi_pool_elective_starvation_not_yet_fixed` (`xfail(strict=True)`), with Risk Analytics as a passing control.

### Investigated: 3 negative-pool majors share the known Part One/Part Two gap
- Live-verified Ecology and Conservation - MSc, Occupational Health and Safety - MHS, and Māori Health - MHS.
- Confirmed all three share the exact same root cause already documented for Geography/Sociology - MA: a Part One credit range correlated with which Part Two pathway is chosen (e.g. Ecology and Conservation's own page: Part One is "Choose between 30 and 60 credits from", Part Two is "Choose between 90 and 120 credits from" - two pathways both summing to 180cr), stored as two independent fixed-size requirements instead of a correlated choice the domain model has no way to express.
- No fix attempted: choosing one arbitrary pathway would be an unsafe data edit. The fix needs the same correlated-choice modelling as Geography's Part One.
- Added `test_correlated_part_one_two_majors_not_yet_fixed` (`xfail(strict=True)`), matching the existing `test_geography_and_sociology_ma_part_one_not_yet_fixed` convention, documenting the live-verified detail per major rather than leaving `_UNRESOLVED_NEGATIVE_ELECTIVE_POOL_MAJORS` as an unexplained skip list. Updated that constant's comment and DATA_QUALITY.md to match.
- Full suite re-confirmed clean: 4 failed / 839 passed / 2 skipped / 13 xfailed (13 = 12 + this one new xfail).

### Fixed: stale free-elective pool sizes for 48 master's majors
- Root cause: every major tree with a trailing, unconstrained `CHOOSE_CREDITS` node (`course_codes: []`) had that node's credit size baked in as `(240 - everything else explicitly modelled)`, using the stale 240cr qualification total instead of the verified total.
- Confirmed before repair: all 51 majors under a length-fixed qualification with exactly one such open node summed to precisely 240cr.
- This is a mechanical correction, not a new curriculum claim. The placeholder means "whatever is left to reach the total", and the total was already independently verified.
- Fixed for 48 of the 51 via new `fix_stale_free_elective_pool_sizes` in `repair_dataset.py`, wired into the repair pipeline as Pass 5, baked into the shipped `datasets/majors.json`. Idempotent, only touches majors with a plain `ALL_OF` root and exactly one open node under an already-length-fixed qualification - 6 new regression tests cover the Chemistry/Mathematics shapes, idempotency, and every skip condition.
- Verified genuinely end-to-end (not just arithmetically): Chemistry and Mathematics - MSc (M/INT) now both produce a real `DegreeValidator`-passing plan with zero errors. Spot-checked 5 more across 4 different qualifications (Statistics - MSc, History - MA, Management - MMgt, Business - Master of Analytics) - all pass.
- **3 majors deliberately left unfixed**: Ecology and Conservation - MSc, Occupational Health and Safety - MHS, and Māori Health - MHS hit the same stale-240 arithmetic, but their corrected open-pool size would be negative. Named in `_UNRESOLVED_NEGATIVE_ELECTIVE_POOL_MAJORS`, explicitly skipped rather than force-fixed or silently ignored.
- One test (`test_build_gap_meta_catches_structural_shortfall_credit_count_misses`) used Chemistry MSc specifically to demonstrate that credit-count-only checks miss real structural failures - fixing Chemistry's actual data broke that demonstration (the plan is now genuinely complete, nothing left to catch). Swapped in Animal Science - MSc, which fails for a different, still-open reason (a named 90cr pool, not the free-electives catch-all) and demonstrates the same gap.
- Also fixed two related test/fixture issues: restored the `normalise_courses` function signature and added `specialisations.json` to repair-dataset fixtures now that `main()` loads it.
- Full suite re-confirmed clean throughout: 4 failed / 839 passed / 2 skipped / 12 xfailed - same known baseline, plus 6 new passing tests for the fix itself.

### Fixed: qualification-length sweep complete
- Checked the final 2 of the 41 Level-9-length-2 qualifications: **PMAGC** Master of Agribusiness and **PMFDT** Master of Food Technology, both confirmed 180cr (stored 240cr), both the same fix as the rest of this sweep.
- All 41 Level-9 `length=2` qualifications are now checked against their official regulations pages: 32 confirmed wrong and fixed, 9 confirmed correct. A 32/41 hit rate confirms `qual_length=2` is a coarse bucket, not a reliable credit total.
- The 6 remaining Level-9 qualifications that already reported `length=1` were not part of this sweep and remain unverified, though a length of 1 is at least plausible on its face given how badly `length=2` performed.
- Full suite re-confirmed clean (4 failed / 832 passed / 2 skipped / 12 xfailed) with all 32 fixes applied - the same baseline as every other entry in this file, meaning none of this changed test behaviour at all. The existing `test_pmart_length_fix_produces_180cr_profile` already covers the shared `(9, 1.5)` profile every 1.5-length fix in this sweep reuses, but nothing previously exercised the `(9, 1.0)` profile PMCNS is the first real user of - added `test_pmcns_length_fix_produces_120cr_profile` alongside it so that path has the same regression coverage.

### Fixed: qualification-length sweep continued
- Continued the sweep from the entry above. Checked 32 more of the 41 Level-9-length-2 qualifications (39 of 41 total now checked) against their own official regulations pages.
- 26 more confirmed wrong the same way (stored 240cr, actually 180cr, all fixed in `_VERIFIED_QUALIFICATION_LENGTH_FIXES`): PMSSD, PMCRW, PMENM, PMMNG, PMAPL, PMCMM, PMEDC, PMHLM, PMINC, PMIND, PMINS, PMDSG, PMPRC, PMBSS, PMHLS, PMVTT, PMEMM, PMCNT, PMSCA, PMCMS, PMMRS, PMFNA, PMSPT.
- One confirmed wrong at a different magnitude: **PMCNS** Master of Counselling is actually 120cr, not 180 or 240 - stored `length=2` is 2x too high rather than 1.33x. Reuses the existing `(9, 1)` `DegreeProfile` (120cr) rather than the `(9, 1.5)` one everything else in this sweep uses. Verified end-to-end that `profile_for(9, 1.0)` resolves correctly at runtime, not just that the dict entry parses.
- 8 more confirmed correct at 240cr, no fix needed: PMCLP, PMMRV, PMRSE, PMNRS, PMPBH, PMPRA, PMBSA, PMEDV.
- Test fixture rebuilt to derive its qualification list directly from `_VERIFIED_QUALIFICATION_LENGTH_FIXES` rather than hand-listing codes, and its "untouched" control switched from PMEDC (now a real fix) to PMNRS (confirmed correct).
- 30 wrong out of 39 checked (32 of 41 including PMART/PMSCN) - the overwhelming majority, not an edge case. Only **PMAGC** (Agribusiness) and **PMFDT** (Food Technology) remain unverified. Full suite re-confirmed clean (4 failed / 832 passed / 2 skipped / 12 xfailed) after applying all 30 total fixes.

### Fixed: 4 more Level-9 qualification lengths confirmed wrong, same root cause as PMART/PMSCN
- Checked 7 more Level-9 qualifications against their official regulations pages, which state total credits explicitly.
- 4 confirmed wrong the same way as PMART/PMSCN (stored `length=2`/240cr, actually 180cr): **PMSPL** Master of Speech and Language Therapy, **PMFDS** Master of Food Safety and Quality, **PMANL** Master of Analytics, **PMFNN** Master of Finance. All four added to `_VERIFIED_QUALIFICATION_LENGTH_FIXES`, source-cited, reusing the existing `(9, 1.5)` `DegreeProfile` entry.
- 3 confirmed correct at 240cr, no fix needed: **PMAPC** Master of Applied Social Work, **PMCLR** Master of Clinical Practice (Nursing), **PMSCW** Master of Social Work.
- 6 wrong out of 9 checked total (including PMART/PMSCN) - confirms this is a widespread problem, not a rare edge case. 34 qualifications remain unverified; see DATA_QUALITY.md for the full remaining list and each one's regulations-page URL.
- Extended the existing generic regression tests (`test_qualification_length_fixes_applies_every_documented_code`, idempotency test) to cover the new entries rather than adding one-off tests per qualification, matching how PMART/PMSCN were already tested.

### Fixed: tests with stale assumptions about English BA
- English - Bachelor of Arts's required non-pool courses cap out at 30cr L200 (`139139` plus a 15cr L200 `CHOOSE_CREDITS` pool), short of the 45cr needed before its 45cr L300 pool (`139305`/`139307`/`139340`) can be scheduled. This is the same documented level-progression limitation already tracked for Chinese, Psychology, Creative Writing, Japanese, Education, and Finance.
- `test_ba_english_plan_is_valid` marked `xfail(strict=True)` with the same shared reason used for the other category-2/3 majors, not silently skipped.
- Rebuilt `test_generator_horizon_counts_active_semesters` on a synthetic six-course sequential-prerequisite chain via `PlanGenerator` instead of a real major, since the test checks semester-counting arithmetic under `no_summer=True`.
- Net result: 6 failed / 831 passed / 11 xfailed -> 4 failed / 832 passed / 12 xfailed. The remaining 4 failures are the pre-existing, unrelated baseline (`test_package_version_matches_pyproject`, `test_plan_shows_campus_exclusion_warning_for_real_major`, `test_overcaptured_major_required_courses_never_silently_dropped`, `test_filler_prerequisite_is_correctly_scheduled`) - checked individually, none touch English or the level-progression rule.

### Fixed: CLI and API now report real structural validation, not just credit-count arithmetic
- Both `cli/main.py`'s "Major requirements: satisfied" message and `api/server.py`'s plan response computed completeness from `degree_total - credits_total` reaching zero - never from the real `DegreeValidator`, which is the only thing that actually knows about named sub-requirements (e.g. a distinct "free electives" pool separate from a major's own required pools). A plan could hit the exact right credit total and still fail a structural requirement, and neither surface's own success message caught it - confirmed concretely on Chemistry - Master of Science, where the CLI printed "satisfied" on a plan the real validator rejects for a 60cr free-electives shortfall.
- Added a real `DegreeValidator` check to both: `api/server.py`'s `_build_gap_meta` now returns a `structural_errors` list (surfaced in both the response meta and as `⚠ Degree requirement not met: ...` warnings); `cli/main.py`'s `_print_summary` runs the same check and prints `Major requirements: NOT fully satisfied` plus each specific error instead of a blanket "satisfied" when it fails. Best-effort in both places - any lookup failure is swallowed silently rather than blocking a plan that already generated fine, and neither is wired up for double majors yet (no combined-tree validator exists - documented, not silently skipped).
- New regression test (`test_build_gap_meta_catches_structural_shortfall_credit_count_misses`) proves this against the exact real case that motivated it: Chemistry MSc, M/INT, `residual_gap == 0` but `structural_errors` non-empty. Verified manually against English - MA (genuinely complete, still prints a clean "satisfied") and Geography - MA (a different, already-documented Part One bug, now visibly flagged instead of silently reported as fine) to confirm no false negatives on top of the true positive.

### Fixed: Master of Science total (240cr -> 180cr) too, and a deeper architectural gap found
- Checked Master of Science the same way as Master of Arts, since its majors already showed the identical Part One/Part Two thesis structure (Animal Science, Chemistry, Mathematics, Agricultural Science, Biological Sciences all confirmed). Its own qualification page states outright: "Massey University's Master of Science is a 180-credit master qualification (a 240-credit MSc is also available)." Added `PMSCN` to `_VERIFIED_QUALIFICATION_LENGTH_FIXES` alongside `PMART`.
- Found something bigger while checking this: Massey's own general qualification-types page states master's degrees "can be 120 credits, 180 credits or 240 credits... depending on study you have done before and academic achievement." Credit totals for taught master's qualifications are genuinely conditional on the individual student's prior qualifications, not a single fixed number per qualification at all. This project's `DegreeProfile` model assumes one fixed total per qualification - there's no pathway-choice input anywhere in the planner for "did you enter with Honours" or similar, so it structurally can't represent this even once every qualification's default number is correct. Defaulting to 180cr for `PMART`/`PMSCN` matches the headline/standard pathway on their own qualification pages, but a 240cr pathway is confirmed to also genuinely exist for at least MSc - the tool has no way to offer it. See DATA_QUALITY.md.
- Verified end to end: Chemistry/Mathematics - MSc now correctly target 180cr (were 240cr). Checking this surfaced a further, separate problem: `DegreeValidator` correctly fails the generated plan on a genuine "free electives" shortfall, but the CLI's own `plan` command reports `Major requirements: satisfied` on the *same* plan, since its summary only checks whether total credits reached the target - it never re-runs the full validator to confirm the specific named pools are actually met. A real student would see "satisfied" and stop looking. Not fixed this round - see DATA_QUALITY.md.
- Did not attempt to verify the remaining ~40 unverified Level-9 qualifications individually this round - see DATA_QUALITY.md for why a page-by-page crawl isn't the right next move on its own.

### Fixed: Master of Arts qualification total (240cr -> 180cr), and what it exposed
- While chasing Education's Part Two bug, the validator reported a 15cr shortfall against "240 required" - which led to finding that 240 was never right for Master of Arts in the first place. It's derived from Massey's own `qual_length` metadata field (2 years) via a `length * 120` default, not from anything Massey publishes per-qualification. Live-verified against Geography's and Education's own subject pages, both stating identically: "Massey's Master of Arts is 180 credits. This means you can complete an MA in 3 semesters of full-time study." 1.5 years, not 2.
- Every one of the 44 Level-9 (Master's) qualifications in `qualifications.json` reports `qual_length=2` except a handful explicitly marked 1 year - itself a sign this field is a coarse category from Massey's backend, not a precise credit-total proxy. Only Master of Arts has actually been checked against a live page so far; the other ~43 are unverified and may or may not be affected - this is now the single highest-priority open item, larger in real-world impact than anything else in this document (see DATA_QUALITY.md).
- Added `apply_verified_qualification_length_fixes` to `repair_dataset.py`, mirroring the existing `apply_verified_prereq_fixes` convention (a named, source-cited override table, not a silent edit to scraped data), and a matching `(9, 1.5)` `DegreeProfile` entry (180cr) in `rules/degree_rules.py`. Applied directly to `qualifications.json` for PMART (Master of Arts). Three new regression tests.
- This is a strict correctness improvement (a plan validating against a wrong total is worse than one that fails against the right one), but it retroactively exposed that 2 of the 3 majors fixed earlier (Geography, Sociology) have a separate, pre-existing Part One bug: several courses stored as flatly required, consuming credits the real qualification treats as a smaller choosable pool (Geography: 6 courses x 30cr = 180cr, the *entire* qualification total, leaving nothing for Part Two). This was invisible against the previous wrong 240cr target - there was enough slack to hide it. Not a regression from this fix; a bug this fix revealed. English - MA already had Part One correctly modelled as choosable pools, so it's unaffected and still passes for real. Test split accordingly: `test_ma_majors_include_exactly_one_part_two_path` now covers English only; `test_geography_and_sociology_ma_part_one_not_yet_fixed` (new, `xfail(strict=True)`) documents the newly-exposed Part One gap.

### Fixed: exact-fit preference, and the ANY_OF fix shipped for 3 of 5 majors
- Found the "prefer a clean single-course fit" behaviour seen in the Quantity Surveying test was never actually designed - `_elective_sort_key` sorts purely by offering timing, level, then code, with no notion of credit-target fit at all. It happened to prefer a standalone 90cr course there and happened to prefer a fragmented Part 1/Part 2 pair for Geography's thesis pool, purely from how those particular course codes sort. Added a real preference: before the greedy sweep, `_select_electives` now checks for a single schedulable course that exactly closes the remaining credit gap and takes it deliberately, instead of leaving the outcome to code-numbering coincidence.
- Applied the `ANY_OF` fix to the 3 of 5 live-verified majors that now produce a fully valid plan end-to-end (checked against real `DegreeValidator`, not just plan content): **Geography, English, Sociology - Master of Arts**. Each has a same-credit standalone alternative (e.g. a 60cr "Research Report") to their thesis pair, so the exact-fit preference above picks it cleanly with zero credit overshoot - no overshoot-tolerance policy decision was actually needed for these three.
- **Education - Master of Arts** does not yet have the fix applied: applying it surfaced a distinct, new bug. The elective top-up pass reaches back into a named pool that's already met its own target once total `elective_budget` exceeds the sum of all named pool targets, adding a second course from the same already-satisfied pool (e.g. selecting both the 60cr and 45cr "Professional Inquiry" variants). The subsequent credit trim then removes the original correct 60cr choice and keeps the insufficient 45cr one, purely by `(-level, code)` removal order. Test split out (`test_education_ma_part_two_not_yet_fixed`, `xfail(strict=True)`) from the now-passing `test_ma_majors_include_exactly_one_part_two_path`, which covers the 3 fixed majors for real.
- **Animal Science - Master of Science**'s thesis-vs-research-report choice (a non-overlapping-codes variant of the same mis-encoding, so `audit_pool_overlap.py`'s code-overlap heuristic can't detect it) still fails in D/DIS mode for the pre-existing, already-documented greedy-ordering limitation (see DATA_QUALITY.md) - untouched this round, not a new finding.
- `audit_pool_overlap.py` now reports 40 majors needing live verification (down from 43 - the 3 fixed ones no longer match its overlap heuristic, since they're `ANY_OF` now rather than two `ALL_OF`-required siblings).

### Correction: the "no per-pool budget reservation" theory (v2.11.0, below) was wrong
- Reproduced the reported failure directly against real data (Geography MA, `AnyOf`-wrapped in memory) rather than trusting the prior write-up. `_select_electives` was not the problem: instrumented every call in the real pipeline and it correctly selected both halves of the Thesis Part 1/Part 2 pool every time. The actual defect was downstream, in `_trim_plan_to_credit_target`.
- Two real, previously undiagnosed bugs, both in `search.py`:
  1. The Part 1/Part 2 pairing safeguard's regex only matched Roman numerals (`Part I`, `Part II`). Every real split-enrolment course in the dataset uses Arabic digits (`Part 1`, `Part 2`) - confirmed by testing the regex against real titles. The safeguard never fired for any of them.
  2. Because of (1), when a pool overshoots its target (both halves selected, exceeding budget), `_trim_plan_to_credit_target` removed pool courses by `(-level, code)` with no concept that two courses were a dependent pair - it could remove Part 1 while keeping Part 2, e.g. `145871`/`145872` (`"145871" < "145872"` alphabetically), leaving a plan with only "Thesis Part 2" and no "Part 1", something a student can never actually complete.
- Also found: this second bug is not specific to the `ANY_OF` scenario. It reproduces today, on unmodified `majors.json`, for any major whose thesis pool overshoots its own budget - currently masked because the pool gets removed to zero credits and backfilled with unrelated filler papers instead, so no student-facing plan currently shows a stranded half. Fixing it is still correct: it removes a real failure mode that the `ANY_OF` fix (and any future majors with tighter budgets) would otherwise hit again.

### Fixed: Part 1/Part 2 pairing, properly this time
- Replaced the dead Roman-numeral-only regex with a marker that recognises both conventions (`Part 1`/`Part I`, `Part 2`/`Part II`).
- Replaced title-text pairing with course-code adjacency (Part 2's code is Part 1's code + 1): verified against every Part 1/Part 2 course in the dataset (123/127 exact matches; the 4 exceptions are genuine data gaps, correctly left unpaired rather than guessed). Title text turned out to be unreliable on its own - many unrelated pairs across different subjects share the exact same generic title (e.g. "Thesis 90 Credit" is reused by dozens of distinct code families), so matching by title alone risked pairing the wrong Part 1 with the wrong Part 2. Code adjacency also correctly handles a few pairs that split credits unevenly (e.g. 30cr Part 1 + 60cr Part 2), which the old equal-credits assumption would have missed entirely.
- `_select_electives`: moved pairing from a pre-emptive check (which wrongly out-prioritised a clean single-course fit, e.g. a standalone 90cr "Research Report", in favour of a split pair) to a post-selection fixup - the ordinary greedy sweep runs first, unchanged, and pairing only completes an orphaned half if the sweep happened to leave one selected alone.
- `_trim_plan_to_credit_target`: pool removal is now pair-aware. If a course being considered for removal has a detected partner, both are removed together or neither is; a course whose partner is protected (required/always-include/preferred) becomes protected too.
- Two regression tests added (`test_select_electives_completes_orphaned_arabic_numeral_part_pair`, `test_trim_plan_to_credit_target_never_strands_part_pair`), both proven to fail against the pre-fix regex/trim behaviour before being trusted. One pre-existing test (`test_bconstruction_honours_plan`, Quantity Surveying's standalone 90cr Research Report) caught a regression in the first version of this fix (pairing was pre-empting the clean single-course fit) - fixed by moving to the post-selection-fixup design above. Full suite: 825 -> 827 passed, same known 5 failures, unchanged.
- Does not yet include the actual `ANY_OF` re-encoding for the 43 majors - these two bugs were prerequisites for it, not the fix itself. Re-attempting it still needs a decision on whether `_select_electives`/trim should ever accept a small credit overshoot to keep a complete pair (e.g. 90cr) intact rather than guarantee an exact credit total, since an atomic 90cr pair can't fit a 60cr budget without either overshooting or being dropped entirely.

---

## [v2.11.0] - 2026-07-21

### Data corrections: live-verified against massey.ac.nz
- `117226`, `117243`, `120303`, `286321`: same flat-AND-of-a-"one of"-list bug as `160212`/`123201` (v2.10.0). All confirmed and fixed against their own pages.
- `241304`/`241305` were flagged by the contradiction audit but confirmed as a false positive: both pages genuinely require `241301` AND `241302` (plus an "or appraisal" alternative the schema can't express). Left unchanged; if there's a real issue it's in `241301`/`241302`'s own restriction data, unverified.
- Animal Science – Master of Science: `majors.json` directly required both `119728` and `162760` as separate COURSE nodes; the qualification's real "Courses you can enrol in" page shows a `CHOOSE_CREDITS(30, [117709, 119728, 162760])` pool instead. Fixed and kept - doesn't depend on ANY_OF, see below.

### Scheduler: third occurrence of the fallback-conflict-check bug
- Fixing Animal Science's Part One pool structure surfaced a real bug: `_select_electives`'s "not enough schedulable courses, include everything" fallback had zero restriction-conflict checking, unlike the main selection loop and top-up pass. `117709` is M/INT-only, so only `119728` counted as D/DIS-schedulable toward the pool's 30cr target, triggering the fallback - which used to add `162760` unconditionally despite it directly restricting `119728`. Fixed; regression test `test_select_electives_fallback_path_checks_conflicts`, proven against pre-fix code.
- Even fixed, Animal Science MSc still can't generate a D/DIS plan - a separate, genuine greedy-ordering limitation, not a conflict bug: `119728` gets picked before the scheduler realizes `162760` alone would have been the only viable completion, and doesn't backtrack. M/INT works today.

### ANY_OF made branch-aware, attempted on 5 majors, reverted on 4 of them
- Found the same mis-encoded Either/Or pattern (see `audit_pool_overlap.py` below) on Geography, Education, English, Sociology (all MA) via their live pages - all four have a real "Either thesis Or research report" Part Two, stored as both required.
- `collect_elective_nodes`/`collect_unchosen_any_of_codes` (`requirement_utils.py`) made `ANY_OF`-aware: picks the cheapest branch's pool instead of flattening every branch as if all were required, and excludes the unchosen branch's codes from `required_codes`. `AnyOfRequirement` was never used in any stored major before this change, so it has zero effect on anything not using it - kept, tested in isolation.
- Applying `ANY_OF` to real majors.json trees (Animal Science's Part Two, plus Geography/Education/English/Sociology) surfaced a second, unresolved problem: `_select_electives` shares one elective budget across all of a major's named pools with no per-pool reservation. Other pools in the same tree can consume the budget the `ANY_OF` pool needs before it's ever considered, or the under-schedulable-pool fallback can starve it - the result being a plan that includes **neither** branch, silently omitting Part Two entirely. Worse than the original both-required bug.
- Reverted: the 4 MA majors back to their original `majors.json` content; Animal Science's Part Two back to the original two-`CHOOSE_CREDITS`-pools-under-`ALL_OF` shape (both required - the original bug, but at least visibly wrong rather than silently incomplete). Animal Science's Part One fix was kept, since it doesn't depend on `ANY_OF`.
- `test_ma_majors_include_exactly_one_part_two_path` kept as `xfail(strict=True)` rather than deleted, matching the existing convention for documented generator limitations.

### New tool: systemic check for the mis-encoded Either/Or pattern
- Built `scripts/audit_pool_overlap.py`: finds ALL_OF nodes with two or more sibling CHOOSE_CREDITS pools whose course codes substantially overlap - the shape of a genuine "Either X Or Y" choice mis-encoded as both required.
- Reports 43 majors, heavily concentrated in Master of Arts specialisations sharing an identical `(60cr, 120cr)` shape - likely one shared page template mis-parsed consistently, not 43 independent bugs. None fixed (see above - even a live-verified fix would hit the same unresolved budget-allocation problem before it could ship). 8 new tests (`test_audit_pool_overlap.py`) against synthetic fixtures, independent of live dataset content.

### Source comment cleanup
- Trimmed narrative comments in `search.py` (3 instances) and `generator.py` (1) down to their essential technical content, and condensed two over-long comment blocks.
- `scripts/run_all_data_refresh.py` had no `--help` handling at all - passing it just silently started the real 35-45 minute scrape. Added a guard that exits instantly with usage instead.

---

## [v2.10.0] - 2026-07-18

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
- Verified against real terminal output end to end (Windows, PowerShell): 7 of 12 reported failures fixed, remaining 5 confirmed pre-existing and unrelated by cross-checking the exact failure list before and after.

### Scraper: request-level failures were opaque in normal runs
- Confirmed on a second real re-scrape: 3 courses hit `status=None, content_length=0` - the signature of `scrape_course_relations`'s catch-all `except Exception`, meaning the request failed entirely (timeout, connection error, DNS failure, or a bug in the scraper itself) rather than returning a real but short HTTP response. All 3 retried and succeeded, so not a functional bug, but the actual exception was only logged at `debug` level - invisible in a normal run, and the WARNING an operator does see ("content_length=0 (expected >= 5000)") looks identical to a genuinely short real response, a different problem with a different fix.
- `scrape_course_relations` now includes the exception's type and message in the result when this path is hit; `_fetch_relations` surfaces it in its WARNING-level log instead of the generic phrasing.
- Regression tests: `test_scrape_course_relations_surfaces_exception_detail`, `test_fetch_relations_includes_exception_detail_in_warning`, both proven against pre-fix code.

### Scraper: confirmed on a second real re-scrape
- Same 4 schema-approximation courses (161222/161250/161251/161380) tripped the regression guard again, exactly as expected and documented - confirms this is a stable, structural interaction, not a fluke of the first run.
- Prerequisite coverage held steady between runs (786 with prerequisites both times; restriction/corequisite counts moved by 1 each, normal live-site churn).

### Data-integrity findings, not fixed here (need live verification against massey.ac.nz)
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
- Live-verified against Massey's Planning Information block: some major requirement choices are expressed as plain prose within a bullet ("one or more of 160105, 160101, 160102", "one of 161111 or 297101") rather than the structured "Choose N credits" widget `major_parser.py` already handled, so they parsed as flat AND requirements. Fixed for the confirmed trigger phrases only, scoped to codes in the same sentence as the trigger. No credit figure is given for this prose form; `credits=15` used as an evidenced default from the checked courses, flagged in DATA_QUALITY.md for spot-verification.
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
- Re-added `PlanGenerator`'s deferred-required-course mechanism (drop a permanently-blocked required course from a tolerant discovery pass instead of failing outright); extended the discovery pass's validation tolerance to also accept a missing required course when that same pass deliberately deferred it.
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
- Same blindness still present in `search.py`'s named elective pool selection (separate code path, not fixed here). Remaining failures also include a Summer-School-only course conflicting with `no_summer` plans, and one test hardcoding a real course's old, now-wrong prerequisite value.

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
