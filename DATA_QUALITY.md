# Data Quality & Improvement Guide

This document explains what data the planner uses, where it comes from, its known gaps, and how to improve it.

---

## Dataset Overview

| File | Records | Source | Last updated |
|---|---|---|---|
| `datasets/courses.json` | 2,766 courses | Massey Swiftype API + page scraping | Scraped 2026 |
| `datasets/majors.json` | 380 majors | Massey Swiftype API + requirement pages | Scraped 2026 |
| `datasets/qualifications.json` | 176 qualifications | Massey Swiftype API | Scraped 2026 |
| `datasets/minors.json` | 39 minors | Hand-curated from the Massey handbook | Hand-curated |

All course `description` fields are auto-generated boilerplate (level/credits/campus summary), not the real Massey course description. Click the ↗ link on any course to see the actual page.

---

## Prerequisite Coverage

| Status | Count (L200-400, undergrad) | Count (L200+, all levels incl. postgrad) |
|---|---|---|
| Has prerequisite data recorded | 770 (66.3%) | 867 (36.4%) |
| No prerequisite data recorded | 391 (33.7%) | 1,512 (63.6%) |

The undergrad-only figure is probably the more useful one for most students. A third of L200-400 courses are missing prerequisite data. The all-levels figure is much higher because many postgrad papers (especially research/thesis courses) genuinely have no prerequisite beyond admission to the programme; that's not all scraping failure, but it hasn't been separated out from genuine gaps, so the UI indicator (below) flags both the same way.

"No prerequisite data recorded" means the scraper didn't capture anything for that course. It does NOT mean the course has no prerequisite. Treat it as "unverified," not "confirmed none."

**UI indicator:** course cards show a small dot next to the course code:
- 🟢 green: prerequisites recorded and satisfied by courses earlier in the plan
- 🟠 amber: prerequisites recorded but NOT yet satisfied by this point in the plan
- 🔵 blue: no prerequisite data recorded for this L200+ course (unverified, not confirmed-none)
- *(no dot)*: L100 course, or a course confirmed to genuinely have no prerequisite

The course drawer shows the same distinction in the Prerequisites section, with a direct link to the course's real Massey page when data is unverified.

**Known specific errors found and fixed during a manual audit** (cross-checked against Massey's live qualification regulations pages). If you find more, the pattern to check is AND vs OR confusion and missing prerequisite chains, not just missing data:
- 159251 (Software Engineering Design and Construction): was recorded with no prerequisite; actually requires 159234
- 159302 (Artificial Intelligence): was recorded as 159234 AND 159201; actually 159201 OR 159234
- 159356 (Software Engineering Capstone): was missing 159352 from its prerequisite
- 159342 (Operating Systems and Networks): was AND, actually OR (159201 or 159234)
- 159352 (Advanced Web Development): had the wrong courses entirely; actually (159100 or 159101) and 158258
- 159361 (Advanced Games Programming): was missing 159235
- 159336 (Mobile Application Development): was AND, actually OR (159234 or 159235)
- 158222 (Data Wrangling and Machine Learning): had the wrong courses entirely; approximated as (159100 or 159101) and (one of 160101/160102/161111/161122). Massey's actual regulation references a "1611xx" prefix pattern that isn't expressible in the current schema, see the note on choose-N/prefix-pattern prerequisites below
- 159333 (Programming Project): real requirement is "three of 1592xx, 1582xx or 2972xx" (a choose-3-from-pool requirement, not "two of 158222, 1592xx" as a previous version of this note stated. That was itself a transcription error, caught during a later audit pass) and approximated as requiring 159201 alone, since this schema has no construct for "N of M courses" as a prerequisite. This is a known approximation, not a verified match, and is now an under-approximation in two ways (wrong N, and not the full pool) rather than one.
- 161222 (Design and Analysis of Experiments): was recorded with no prerequisite at all; real requirement is "1611xx". Approximated as an OR of 161101/161111/161122/161140, the 1611xx courses that currently exist in the dataset. This was found during an audit of Statistics specifically, after the initial fix pass above only covered Computer Science courses. A reminder that a clean fix list for one subject doesn't mean other subjects are clean too.
- 161250 (Data Analysis): was recorded as requiring 161111 specifically, too narrow; real requirement is "1611xx or 297101". Approximated the same way as 161222, plus 297101.
- 161251 (Regression Modelling): same issue and same fix as 161250. Real requirement is also "1611xx or 297101".
- 161380 (Statistical Analysis Project): was recorded with no prerequisite; real requirement is "Two 1613xx courses" (a choose-2-from-pool requirement), approximated as requiring 161304 alone (the same single-course-stand-in approach as 159333 above). This course is Graduate-Diploma-only with no current DIS offerings, so the approximation has no practical effect on undergraduate plan generation; included for data correctness, not because any current plan depends on it.

These four Statistics fixes are implemented in `coursemap/ingestion/repair_dataset.py`'s `apply_verified_prereq_fixes` / `_VERIFIED_PREREQ_FIXES` (with full source citations in that module), run as part of the normal repair pipeline (`python -m coursemap.ingestion.repair_dataset`), rather than as one-off manual edits to courses.json, so they're reproducible if the dataset is ever re-scraped from scratch, and have dedicated regression tests in `tests/test_repair_dataset.py`.

### How to fix prerequisite, restriction, and corequisite data (requires Windows/Mac with internet access)

**Step 1: Test connectivity:**
```bash
python scripts/test_prereq_scraper.py
```
Expected output: 5 courses scraped, showing prerequisites, restrictions, and corequisites for each (most will show `restrictions: []` and `corequisites: []`, since most courses genuinely have neither; 159201 in the test set has a known real restriction, so its line should show `restrictions: ['159271']`. If it shows `[]` instead, don't trust a full run yet, see the warning the script itself prints).

**Step 2: Run the full refresh (~2-3 hours for all 2,766 courses):**
```bash
python -m coursemap.ingestion.refresh_prerequisites
```
This fetches each course's Massey page once, and from that single fetch parses real AND/OR prerequisite logic plus flat restriction and corequisite code lists, then updates `courses.json` with all three.

**Options:**
```bash
# Only re-scrape courses with no prerequisite data (faster):
python -m coursemap.ingestion.refresh_prerequisites --only-missing

# Test with first 50 courses:
python -m coursemap.ingestion.refresh_prerequisites --limit 50

# Reduce concurrency if getting rate-limited:
python -m coursemap.ingestion.refresh_prerequisites --concurrency 5
```
Note `--only-missing` is keyed on prerequisites only (skips a course if its prerequisites are already a structured dict/str). It does not have an equivalent signal for restrictions/corequisites, since an empty list is indistinguishable from "genuinely has none" once a course has been scraped once. The first full run after upgrading to this version should be a plain run without `--only-missing`, so every course's restrictions/corequisites get scraped at least once.

**Known schema limitation:** the prerequisite expression tree only supports AND/OR over fixed course codes. It cannot express "choose N of M courses" (e.g. 159333's "two of 158222, 1592xx") or prefix-pattern alternatives (e.g. "any 1611xx-coded course"). Courses with this kind of requirement are necessarily approximated. If you're extending this dataset, search for other courses with similarly-phrased regulations before assuming a simple AND/OR captures them correctly. Restrictions and corequisites have the same limitation one level simpler: they're stored as flat code lists with no choose-N structure at all, so "Corequisites: one of X, Y, Z" collapses to a flat `[X, Y, Z]` with the choose-one meaning lost.

---

## Restrictions and Corequisites

As of the version that first found this, `restrictions` and `corequisites` were `[]` for all 2,766 courses in `courses.json`. This is not a reflection of most courses genuinely having neither; Massey's course pages commonly list both (e.g. `159201 R 159271`, `125803 C 125702`). It's because nothing in the ingestion pipeline ever looked for these sections: `fetch_courses.py` hardcodes them empty at discovery time, and `prerequisite_scraper.py` (before that version) only ever searched for a "Prerequisite(s)" section.

**The first scraper fix was itself wrong, caught before it could write bad data.** `find_restriction_text`/`find_corequisite_text` were added, but a live connectivity test against 159201 (which has a real, known prerequisite and restriction) came back with *both* empty, not just the new restriction field, prerequisites too. Diagnosing the raw HTML showed why: Massey's current page structure puts the section heading (`<h3 class="course-intro__col-heading">`, e.g. "Prerequisite courses") and the actual course code (`<div class="rich-text">`) in *separate* sibling divs, both children of a shared wrapper, one level apart from what the scraper assumed. The scraper's fallback strategy (heading → immediate next sibling) instead landed on a sub-label div (`<div class="course-intro__col-subheading">`, e.g. "Complete first"), which has no course code in it, found zero codes, and silently returned "no prerequisites found", indistinguishable from a course that genuinely has none. This had presumably been silently wrong for prerequisites too, for however long Massey's site has used this layout, not just newly wrong for the restriction/corequisite addition.

Fixed with a dedicated strategy (`_find_labelled_text`'s Strategy 1) that targets the verified real structure directly: find `.course-intro__col-header`, check its `.course-intro__col-heading` for the section label, then read the code from the *sibling* `.rich-text` div, not the heading's own next sibling. Locked in with a regression test using the verbatim real HTML fetched from massey.ac.nz (`test_find_prereq_and_restriction_real_massey_structure` in `tests/test_prerequisite.py`), not a simplified guess at the structure.

**Lesson for next time a scraper needs fixing here**: a connectivity smoke test that only checks "did we get a 200 and parse *something*" isn't enough, `scripts/test_prereq_scraper.py` was returning cleanly successful-looking output (`prereqs: None restrictions: []`) while being completely wrong. What caught this was checking the result against a *specific known course with a specific known answer* (159201 should never show an empty restriction), and when it didn't match, pulling the raw HTML rather than trusting the parsed output. Any future scraper fix should do the same: verify against at least one course where the right answer is already known independently, not just "did it run without crashing."

The scraper now looks for restriction and corequisite sections too (`find_restriction_text`, `find_corequisite_text` in `prerequisite_scraper.py`), and `refresh_prerequisites.py` writes all three fields from a single page fetch per course. But the code fix and the data fix are two separate steps: this repository's `courses.json` will keep showing empty restrictions/corequisites for every course until someone with real network access to massey.ac.nz runs Step 2 above.

**This isn't cosmetic.** `coursemap/planner/generator.py` already has real logic that blocks scheduling a course if it's in the completed set's restrictions. That logic is correct, but has been silently unreachable for every plan ever generated by this tool, because `course.restrictions` has always been empty. Until the refresh is run, a generated plan can legally contain two mutually-restricted courses with no warning. Treat repopulating this data as higher priority than most other items in this document, since it's the one gap with a "students get an incorrect plan and are never told" failure mode rather than a "plan is less optimal than it could be" one.

---

## Offering Data Gaps

**323 courses** (marked with `?` in the UI) are required in major programmes but have no confirmed 2026 offering data. These were given inferred offerings based on:
- Patterns from other courses in the same subject prefix
- Whether the course title suggests it is a flexible "Special Topic" or thesis

To get real offering data, the scraper must be re-run. The full refresh pipeline is:
```bash
python -m coursemap.ingestion.build_dataset
```

---

## Majors with Weak Data

**4 majors** have no specific required course codes (entire degree is "free electives"):
- Biological Sciences – Postgraduate Diploma in Science and Technology
- Expressive Arts and Media Studies – Bachelor of Communication
- Without Specialisation – Graduate Certificate in Arts
- Without Specialisation – Graduate Diploma in Arts

**89 majors** have >200cr of free elective gaps (the major requirement tree only specifies a subset of the degree).

For these majors, the planner fills electives automatically but the result is not based on real programme regulations.

**~36 majors (9.5%)** have scraped data listing more "required" courses than the degree's credit target allows for. For example, a 120cr diploma whose major data lists 165cr of compulsory-looking course codes. This is concentrated in postgraduate Psychology, Education, and Māori Studies programmes, and is almost always because the source data flattened several alternative specialisation tracks into one list, rather than the degree genuinely requiring more credits than it awards.

The planner copes with this by capping the *droppable* portion of the required-course list to fit the credit budget, but it will never drop a course the degree's own validation tree explicitly checks as required, even if that means the final plan ends up *over* the degree's credit target. This was a deliberate fix made after auditing this dataset: an earlier version of the trim logic counted only each kept course's own credits with no visibility into prerequisite-chain cost, which let it sometimes drop a genuinely-required course purely because the (incomplete) credit math looked like there was room to spare, producing a plan that *looked* complete (right total credits) but silently failed validation for whichever course got dropped. An over-the-target credit total is a more honest failure mode than a plausible-looking one that's secretly missing a required course: it's visibly wrong rather than invisibly wrong.

For a handful of majors with this pattern, the result is therefore a plan that legitimately can't fit within the stated degree length using only DIS-offered courses. That's a real fact about the source data (more required courses + prerequisite chains than the degree credits for), not something a planning algorithm can paper over. The actual fix is re-scraping these specific majors' requirement pages and modelling the alternative tracks as real choice structures, not a smarter scheduler.

---

## The 45cr Level-Progression Rule

Massey's General Regulations (for undergraduate degrees, diplomas, certificates, and graduate diplomas/certificates) include a rule separate from any individual course's prerequisites: **a student cannot enrol in a 200-level course without 45cr passed at 100-level, nor in a 300-level course without 45cr passed at 200-level.** This applies regardless of whether any specific course names a prerequisite. It's a blanket progression gate, and it does not apply to postgraduate qualifications (NZQF level 8+), which are gated by programme admission instead.

This rule was not enforced anywhere in the planner until this audit, even though `courses.json` has everything needed to check it. The generator (`coursemap/planner/generator.py`) now enforces it during scheduling and during both rebalancing passes, gated on qualification level so postgraduate majors (e.g. the Master of Specialist Teaching family, which routinely has required L300 courses with no L200 chain at all) are correctly exempted.

Turning this rule on surfaced real, pre-existing problems across a substantial share of the dataset. A random sample of 40 undergraduate majors found only 8 (20%) currently produce a `generate_filled_plan` plan that genuinely satisfies all of the major's own elective-pool requirements once checked properly (`keep_open_pools=True`, not just a credit-total check, see below for why that distinction matters). The other 32 split into three genuinely different categories, confirmed by testing each one with the rule forcibly disabled to isolate cause:

**1. Pre-existing failures unrelated to this rule (~12 of 40 sampled).** Things like a required course only offered in Summer School while `--no-summer` is set (Environmental Science, Ecology and Conservation, see the separate Summer School note elsewhere in this file), or majors with zero DIS offerings at all (several Bachelor of Design majors, evidently on-campus-only programmes). These fail identically whether the level-progression rule is on or off, confirming they predate this audit entirely.

**2. Required courses that cannot, by themselves, reach the credit needed to unlock a later required course (~6 of 40 sampled, e.g. Te Reo Māori, Educational Psychology, Media Studies, Linguistics, Property).** `_repair_level_progression`'s swap/drop mechanism only ever touches *elective pool* selections. Required (non-pool) courses are always kept, by design, since dropping an actually-required course would silently produce an incomplete degree. When the required-course list itself doesn't add up to 45cr at the level below a later required course, there's nothing the scheduler can rearrange; the major's required-course list, as scraped, is genuinely incomplete for a DIS student following only what's listed as required. This is the same root cause already documented for Chinese, Bachelor of Arts (below), confirmed, not a new bug, just newly visible because nothing previously checked for it.

**3. Named elective pools that cannot, on their own, supply enough lower-level credit to justify their own higher-level selections (~13 of 40 sampled, e.g. Accountancy, Spanish, Japanese, Psychology, Ecology and Conservation, Business Analytics, Software Engineering).** `_select_electives` (in `coursemap/optimisation/search.py`) picks each pool's minimum-cost subset independently, with no visibility into whether the combined selection across pools satisfies the 45cr rule. A repair pass (`_repair_level_progression`) handles same-pool swaps (trading a higher-level pool member for an unselected lower-level one from the *same* pool, since pool credit can't cross-subsidise (confirmed the hard way: an early version that swapped across pools silently broke the donor pool's own target)) and, when no swap exists, drops the unschedulable higher-level selection so the *discovery* pass doesn't deadlock the whole search. This successfully avoids exceptions, but the resulting credit shortfall can only be closed by **courses that are members of that specific named pool**.
`DegreeValidator`'s `ChooseCreditsRequirement` check (`coursemap/validation/engine.py`) only counts a pool's own listed `course_codes`, so generic filler from outside the major, however well it's prioritised, structurally cannot satisfy it.

  An `ElectiveFiller` "level-gate-aware" tier was built and tested specifically to try to close this (see `needed_levels` in `coursemap/planner/elective_filler.py` and `PlannerService.last_needed_levels`). It correctly biases filler toward the level a gate still needs, and it did fix one separate, real bug along the way (the tier was initially sorted by *shortfall amount* rather than by level, which could let it select an L200 filler course before enough L100 credit existed to make that very course schedulable (found via this same sweep, fixed, confirmed against Spanish, Business Analytics, and Japanese, which no longer throw an exception). But it cannot and does not close the *named-pool-satisfaction* gap itself, because the credit it adds isn't a member of the pool the validator checks. Properly fixing this needs either a schema change (letting a course count toward a named pool's target even when sourced from outside the major, itself a real-world question of whether Massey actually intends that) or a data-modelling correction (the named pool's course list may not be the only way Massey intends a student to satisfy it). Left as a documented limitation, not worked around with a smarter filler. That path was tried and shown not to work.

A handful of majors from category 3 are marked `xfail(strict=True)` in `tests/test_integration.py` as concrete, regression-tested examples (Ecology and Conservation, Psychology [implied by Chinese's pattern], Accountancy, Chinese, Japanese, Creative Writing, Finance, Education) rather than silently skipped, so the suite fails loudly if this regresses further, and `test_filled_plan_reaches_degree_target` itself was strengthened to check actual pool satisfaction (`keep_open_pools=True`) rather than just the credit total. The credit-total-only version of this test was passing for several of these majors even before that fix, which is exactly how this systemic issue went unnoticed for as long as it did.

**Chinese, Bachelor of Arts** (category 2 above) was the first case found, before the broader sweep: it has only 30cr of required L200 courses (`241201`, `241202`) and no required course that reaches the 45cr needed to unlock its L300 courses. The major's L200/L300 elective pool exists but is advisory-only (`subject_hint`, not a real choice structure), so the planner has no principled way to know a student should deliberately pick a third L200 Chinese elective. A real student in this position would need either a Course Advisor override or to self-select extra L200 papers. This is a fact about the major's required-course list, not a bug in the scheduler.

---

## Level Distribution (max 165cr at 100-level / min 75cr at 300-level)

Separate from the 45cr level-*progression* rule above (which gates *when* a course becomes schedulable), most 360cr Level 7 bachelor's degrees also carry a level-*distribution* rule on the finished plan as a whole: verified against live regulations for BSc, BA, BCom, and BInfoSci, all four specify "not more than 165 credits at 100-level" and "at least 75 credits at 300-level" (Bachelor of Business is a known exception at 180cr, not 165, see the caveat comment on `_DEGREE_PROFILES` in `degree_rules.py`).

`degree_rules.py`'s `DegreeProfile` has always computed the correct numbers for this (`max_level_100=165`, `min_level_300=75` for `profile_for(7, 3)`), but `build_degree_tree` never turned them into `MaxLevelCreditsRequirement`/`MinLevelCreditsRequirement` nodes, so the constraint was silently never checked, on any plan, ever. The node classes themselves, their serialization, and their UI rendering were all already fully built and tested, they were just never constructed by anything.

**Two attempts to wire this in, both reverted, for two different reasons.**

**Attempt 1** just constructed the nodes from the profile and enforced them. Reverted immediately: `ElectiveFiller`/`PlanSearch` had no concept of level distribution to aim for while filling, they'll happily fill a plan mostly with 100-level electives if those are the most convenient schedulable candidates, with nothing steering credits toward 300-level or away from 100-level as the totals accumulate. 17 tests failed; concretely, **Computer Science – Bachelor of Information Sciences** generated at 195cr/165cr-cap at 100-level and 60cr/75cr-min at 300-level, **Mathematics – Bachelor of Science** failed the same way, and **Human Nutrition – Bachelor of Science** landed at 345cr/360cr total as a knock-on effect.

**Attempt 2** fixed exactly that: `PlannerService._level_distribution_state` computes how much L100 room is left and how short of the L300 floor the plan is, and `ElectiveFiller` got a dedicated `level_credit_limits` hard cap plus its own priority tier for the distribution floor (`level_floor_priority`, Tier 1, one below the existing level-progression Tier 2, see `ElectiveFiller`'s class docstring for why they can't share a tier or a dict: doing so first caused a starvation bug where a real case, Creative Writing–Bachelor of Arts, marked L100/L200/L300 all "needed" via the same mechanism, and since that tier sorts level-ascending, the L100/L200 entries consumed the whole fill budget before the ranked list ever reached L300). This fixed the two majors Attempt 1 broke. But turning the hard validation back on with this fix in place surfaced a **second, unrelated, pre-existing issue**: `PlanSearch._select_electives` always fully satisfies every elective pool's own nominal `credits` target, completely independent of the `elective_budget` parameter passed in (only its zero-credit-pool top-up pass, and an explicit over-capture cap, actually look at that budget). When `generate_filled_plan` injects a filler pool alongside a major's own already-sized pool, the two pools' nominal targets simply add together rather than sharing one combined budget. This was already happening before either level-distribution attempt, just invisible, since `TotalCreditsRequirement` uses `>=`, so a plan with a few too many total credits never failed validation. A hard per-level cap is the first constraint sensitive enough to notice the overshoot: **Computer Science – Bachelor of Science** (with prior/transfer credits in the plan) generated at 210cr/165cr-cap at 100-level, and Creative Writing reappeared at 195cr/165cr-cap even with the Tier 1 fix in place, because the extra credit wasn't coming from the filler's own selection (which was correctly capped), it was coming from the major's own pool being independently over-satisfied on top of it.

Fixing that needs changes to `_select_electives`'s pool-budget accounting in `search.py`, sharing one running budget across every known-credit pool (the major's own plus any injected filler pool) instead of letting each pool's nominal target stand alone, a separate, larger piece of work than this feature's own wiring, since `_select_electives` is a ~250-line function used by every plan generation path, not something to touch inside a single-issue fix without its own dedicated pass and test sweep.

**What's shipped vs what isn't:** `PlannerService._level_distribution_state` and `ElectiveFiller`'s `level_credit_limits`/`level_floor_priority` mechanism are kept, they're correct on their own and make filler selection more sensibly distributed even without hard enforcement (see `tests/test_units.py::TestDegreeRules` and `ElectiveFiller`'s own tests). `build_degree_tree` still does not emit `MaxLevelCreditsRequirement`/`MinLevelCreditsRequirement`; `test_build_degree_tree_does_not_yet_emit_level_constraints` pins this so a future attempt has to consciously revisit it, and should fix `_select_electives`'s budget-sharing first, not after. Reported as a known gap rather than a quiet partial fix, per this project's standing rule of not calling something fixed without verifying it end-to-end.

---

## Minors

The 39 minors in `datasets/minors.json` are hand-curated from the Massey handbook. They are approximate:
- Course code lists may not match the current year's handbook
- Level requirements (L100/200/300 credit splits) are typical but may vary by programme
- These have NOT been individually cross-checked against live Massey pages the way the Computer Science prerequisite chain was. Treat them with the same "verify before enrolling" caution as any unverified prerequisite data

To add more minors, edit `datasets/minors.json` following the existing structure.

---

## Re-scraping the Full Dataset

> ⚠️ Requires Massey's website to be accessible (blocked in some server/CI environments).

```bash
# Full re-scrape (takes several hours):
python -m coursemap.ingestion.build_dataset

# Faster: only refresh courses, not majors/quals:
python -m coursemap.ingestion.refresh_prerequisites

# After any re-scrape, repair the data:
python -m coursemap.ingestion.repair_dataset
```

After re-scraping, restart the server. The dataset is cached at startup.

