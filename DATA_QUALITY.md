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
- 160212 (Discrete Mathematics): was recorded as a flat AND of every code in both prerequisite clauses (effectively requiring all ten first-year courses at once); real requirement, live-verified, is "one of (160101, 160102, 160103, 160105, 160111, 160112, 160132, 160133, 228171 or 228172) and one of (159101, 159171 or 230112)" - two independent choose-one clauses. This was the cause of Mathematics, Bachelor of Science appearing self-contradictory (see below): it directly requires both 160101 and 160102, and the mis-scraped AND then also forced in 160105 via 160212, which mutually restricts both. Fixed by this correction alone; no scheduler change needed.
- 123201 (Chemical Energetics): was recorded the same way as 160212 above - a flat AND of every code in both clauses, requiring 160101 AND 160102 AND 160105 simultaneously (self-contradictory, since 160105 restricts both). Real, live-verified: "one of (123102, 123105, 124104 or 123172) and one of (160101, 160102, 160105, 160132 or 160133)". This is stale data, not a current parser gap - `parse_prerequisite_text()` already returns the correct tree for this exact phrasing, confirmed by testing it directly. Fixed by this correction; this was the actual cause of Chemistry, Bachelor of Science failing to generate.

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

The scraper now looks for restriction and corequisite sections too (`find_restriction_text`, `find_corequisite_text` in `prerequisite_scraper.py`), and `refresh_prerequisites.py` writes all three fields from a single page fetch per course. The live re-scrape has since been run: restrictions went from 100% empty to 75.6% empty, corequisites 100% to 93.6% (most courses genuinely have neither, that's expected).

**This isn't cosmetic.** `coursemap/planner/generator.py` already had real logic that blocks scheduling a course if it's in the completed set's restrictions. That logic was correct, but had been silently unreachable for every plan ever generated by this tool, because `course.restrictions` was always empty. It's live now.

---

## The old prerequisite data was cross-contaminated

Diffing the re-scraped `courses.json` against the pre-refresh version turned up 342 courses (out of 869 that had a non-empty prerequisite before) where the old value disappeared after the refresh. That's a big enough number to be worth checking rather than assuming the new scraper regressed, so a sample was checked directly against live Massey pages.

All three checked were the old data being wrong, not the new scraper missing something. The clearest case: six unrelated 300-level Sport & Exercise papers (`234360` Sport Psychology, `234361` Exercise Psychology, `234216` Sport and Community Development, `234346`, `234312`, `234331`) all had `234236` (Applied Sport Coaching) listed as their prerequisite. `234236` itself has no prerequisite and isn't a logical gate for any of them, per the live regulations it's only a restriction target for an unrelated course. The old scraper was picking up the same course code across a run of unrelated pages, almost certainly bleeding in from a "related courses" widget or similar shared page element rather than the actual Prerequisite(s) section. `275320` and `234360` were checked the same way and showed the same pattern: a specific-looking prerequisite in the old data that simply isn't on the live page at all.

Net effect: the re-scrape is a real, net improvement, even though the empty-prerequisite rate went up (68.6% → 71.6%) rather than down. A higher empty rate here means "the scraper now correctly says there's nothing" more often, not "the scraper is missing more."

---

## ElectiveFiller had no idea restrictions existed

Turning on real restriction data exposed a bug that could never have been caught with synthetic test fixtures, since restrictions were always `[]` until the re-scrape above actually ran: `ElectiveFiller` picks free-elective and named-pool filler courses with zero awareness of the `restrictions` field. A course like `159100` (Programming for Engineering and Technology), restricted against `159101`, would get recommended as filler even when `159101` was already a required course elsewhere in the same plan. `generator.py`'s restriction check (correctly) then rejected the whole plan rather than the filler just picking something else, which is a much worse failure mode for a student than just not seeing that one course suggested.

Same shape of problem as the level-distribution issue elsewhere in this document: a real constraint existed and was correctly checked, but nothing upstream steered candidate selection away from it, so a check that should prevent one bad course from being suggested instead took down the entire plan.

Fixed in `ElectiveFiller.rank_candidates`/`select_to_fill`: candidates are now excluded if their own restrictions overlap with anything already in the plan, or if anything already in the plan restricts against them (scraped restriction data isn't guaranteed to list both directions, Massey's own pages don't always cross-reference each other either, so both directions are checked). Also tracks restrictions introduced by selections made within the same fill pass, since ranking happens once upfront, two candidates that restrict each other could otherwise both pass the initial ranking and both get picked in the same batch.

This fixed roughly a third of the test failures that showed up once real restriction data was in place (a full undergrad-major sweep went from 45 to 37 genuine D/DIS failures, out of 111 majors, after excluding the ~17 majors that are legitimately on-campus-only and were never solvable at D/DIS to begin with). **Not a complete fix.** The same blindness still exists in `search.py`'s `_select_electives`, which handles a major's own named elective pools rather than free-elective filler, that's a separate code path this change doesn't touch. The remaining ~31 failures are a mix of that gap, a genuinely separate double-major-specific issue (see below), and a course that's only offered in Summer School conflicting with `no_summer=True` plans.

---

## Double majors: all three original root causes now understood, two fully fixed, one open

All 22 double-major test failures traced back to exactly 3 distinct major-pair scenarios once actually catalogued (rather than fixed one at a time): Computer Science + Mathematics, Computer Science + Statistics, and Finance + Marketing. All three are now understood; the first two are fully fixed.

**Root cause 1 (fixed): mutually-restricted "choose one" courses hard-required as a *specific* variant per major.** Massey offers several parallel variants of the same underlying requirement, mutually restricted against each other so a student only takes one (e.g. "Science and Sustainability for ICT" 247112 vs "...for Science" 247113; "Applied Statistics" 161111 vs "Statistics" 161122 vs two others). A previous fix for the level-progression rule had hardcoded a *specific* variant into each of 19 BSc/BInfoSci majors depending on subject flavour. That's correct for any single major on its own, but Computer Science requiring 247112 while Mathematics requires 247113 (both mutually restricted) makes the *combination* structurally impossible, since a student literally cannot enrol in both. Fixed by converting each major's hardcoded single-course requirement into a shared `CHOOSE_CREDITS` pool listing all known mutually-restricted variants (15 majors touched for the 247xxx cluster, 2 for the 161xxx cluster), so any one satisfies the requirement, matching how Massey's real enrolment works. Verified no course within either affected major's own curriculum depends on the specific variant that was previously hardcoded (checked for any prerequisite naming that exact code non-optionally) before making the change.

**A second bug surfaced while fixing the first**, in `_select_electives`'s pool-selection logic (`search.py`): when a course is both a pool option for one major and a direct hard requirement for another (e.g. Mathematics still hard-requires 161111 directly, which is also one of the 4 options in the new shared pool), the pool's own credit accounting didn't recognise that the required course already satisfied its target. It stripped the overlapping code out of its own candidate list entirely (rather than just not re-selecting it) and went looking for a *second*, independent 15cr from the remaining options, which could easily be a mutually-restricted variant of the one already required. This is what turned "Computer Science + Mathematics" from working (whichever variant CS's pool picked, if it happened to differ from what Mathematics required, this bug would silently break it) into intermittently broken depending on pool sort order. Fixed by keeping the overlapping code in the pool's own candidate list (so its credit contribution is counted correctly) and passing the already-required set into `_select_electives` so it's recognised as already selected rather than reselected. This is the same shape of gap as `ElectiveFiller`'s missing restriction-awareness (see above): a real constraint existed, nothing accounted for it correctly across two independently-authored requirement trees being merged.

**A third, unrelated bug found investigating the second**: Massey's real prerequisite for `161324` (Data Mining) is "one of 161122, 297101, 161220, 161221, 161250 or 161251" (any single one satisfies it), but the scraper's tokenizer always treats a comma as AND, so a flat "one of A, B, C or D" enumeration (no parentheses) parsed as "A and B and C and (D or E)" instead of "any one of A, B, C, D, E". Fixed by detecting a leading "one of"/"any of" marker before a flat comma-separated run and normalising those commas to "or" before tokenizing; parenthesised "one of" clauses that already use explicit "or" internally are untouched. Like the restriction-scraping fix earlier, this is a code fix that doesn't retroactively correct already-scraped data (the original page text isn't kept once parsed), so it only takes effect on the next full re-scrape. `161324`'s specific value was corrected manually as a verified one-off in the meantime (confirmed against the live page directly, not inferred).

**Root cause 2 (fixed): no shortfall-tolerant discovery pass for double majors.** Finance + Marketing (both Bachelor of Business) combined have exactly one unconditional required course between them that isn't part of either major's own elective pools, and it's L300 with zero L100 credit available anywhere in either major's own requirements to ever unlock it. `generate_best_plan`/`generate_filled_plan` (single major) tolerate this kind of shortfall during an internal discovery pass and let `ElectiveFiller` close the gap before a final strict pass; `generate_double_major_plan`/`generate_filled_double_major_plan` never got the same treatment.

A first attempt made the discovery pass unconditionally tolerant and was reverted after it net-negatively affected the full suite (32 failures became 33, previously-working double majors broke, see CHANGELOG.md v2.5.0): changing discovery behaviour for *every* double major, not just the one that needed it, changed pool-selection results for majors that were already fine. The second attempt fixed that specifically: `generate_double_major_plan` now tries the exact original strict call first, completely unchanged, and only on failure retries with a tolerance flag, so a double major that already succeeds is provably unaffected (the fallback code never runs for it at all).

Getting the fallback itself to work end-to-end needed two more pieces: (1) `PlanGenerator` gained a `deferred_codes` mechanism, when a *required* (non-pool) course is permanently blocked by level progression, it's dropped from that discovery pass instead of raising, and the resulting smaller plan correctly produces a bigger gap for `ElectiveFiller` to fill; (2) the existing shortfall-tolerance validation check only recognised "a named pool came up short of its own target" as an acceptable gap, not "a required course is entirely missing", so a deferred required course still failed validation immediately even though deferring it was intentional. Extended that check to also tolerate a missing required course specifically when it's in that same pass's own `deferred_codes`, mirroring the existing pool-shortfall tolerance exactly. Verified: Finance + Marketing now produces a complete, valid 360cr plan with the previously-blocked course correctly scheduled once filler supplies the missing foundation credit, and the full suite has zero regressions from this change (checked specifically for any double major that previously passed and now doesn't; none).

---

## Single-major sweep: the same parser bug affects far more than double majors

Everything above this point was found chasing double-major failures specifically. Running the same kind of sweep across all 111 undergrad majors as *single* majors (not combined with anything) found **25 of 111 (22.5%) completely failed** to generate any plan at D/DIS, once the 17 majors that are genuinely on-campus-only (Wellington/Auckland Design and Screen Arts, Animal Science) are excluded. That's a much bigger problem than the double-major cluster, and it's the same root cause discovered there: the "one of A, B, C or D" parser bug (see "The old prerequisite data was cross-contaminated" and the double-major section above), just showing up in more places once actually looked for systematically.

**Found a reliable way to detect this bug across the whole dataset without re-scraping.** A course's prerequisite is stored as an AND of several codes; if every one of those codes is mutually restricted against every other one (checked using the restriction data, which was scraped correctly), then the AND is a logical impossibility, you cannot simultaneously enrol in courses that are pairwise mutually exclusive, so it's essentially certain the real requirement was "one of these", not "all of these", and the scraper's known comma-handling bug produced an AND where an OR belonged. This isn't a guess: it cross-validates one already-correct field (restrictions) against a field with a known bug class (prerequisites) to find where the second one is provably wrong, independent of needing the original page text back.

Ran that detector plus manual verification against live Massey pages for cases it couldn't catch automatically (its strict pairwise-mutual check missed a few where the stored data was partially corrupted, e.g. a bare `null` sitting where a code should be from an earlier bad parse), and corrected **5 more verified one-off values**: `117201`, `117202` (an "Introduction to Animal Production" cluster, affecting Farm Management, Equine Science, Animal Nutrition and Growth, Sustainable Climate Systems), `123305` (Contemporary Topics in Chemistry, a nested case: "one of these 6 sciences and one of these 4 sustainability courses", previously "all 6 and all 4"), `289250`, `289350` (a Screen Arts professional-cultures pair). Combined with the earlier `161324` fix, that's 6 manually verified corrections this pass. Single-major sweep improved from 69 to 71 out of 111.

**This is still a stopgap, not a fix at scale.** Manually verifying and correcting individual courses one at a time doesn't scale to whatever the true remaining count is, and the automated detector is a heuristic (only catches strict pairwise-mutual-restriction cases, misses anything with a nested or partially-corrupted structure). The parser itself is already fixed (see the double-major section above), so **the real fix is running `refresh_prerequisites` again**: every instance of this bug, however many there are, gets corrected in one pass, instead of finding them one at a time by tripping over which major happens to need the broken course.

## Chemistry – Bachelor of Science: a course's own prerequisite is self-contradictory

**Chemistry – Bachelor of Science**, resolved: `123201` ("Chemical Energetics")'s own stored prerequisite was `160101` AND `160102` AND `160105` AND one of `160132`/`160133` - but `160105` mutually restricts every one of the other three codes in that same AND clause, self-contradictory in complete isolation. Live-verified: the real requirement is "one of (123102, 123105, 124104 or 123172) and one of (160101, 160102, 160105, 160132 or 160133)" (see corrections list above). Confirmed by direct test: `parse_prerequisite_text()` already returns the correct tree for this exact phrasing - this was stale data from before that fix shipped, not a current parser gap. Fixing it resolves Chemistry generation entirely, including the `247xxx` graduate-profile pool correctly picking one variant (the previously-documented "picks 3 instead of 1" symptom this note used to describe was a stale diagnosis of the same underlying `123201` problem, not a separate bug). `123331`, `123332`, `141395` (all transitively require `123201`) should also benefit; not individually re-checked.

---

## Double majors are sensitive to which semester they start in

Verifying the fix above turned up a separate, real issue: at least two more major-pair combinations are blocked, but only for one of the two starting semesters. Computer Science + Statistics (BSc) fails starting in S2 but works starting in S1; Computer Science + Data Science (BInfoSci) is the reverse, fails starting in S1 but works in S2. Neither involves Finance, Marketing, or any of the mutually-restricted-variant clusters fixed above, different courses, different mechanism. The Computer Science + Statistics case traces to `159224`/`159323` (both just options within a 10/12-option elective pool, not required directly) needing `160105` via their own prerequisite chain, which is restricted against `160101` (a course Statistics directly requires) -- a real conflict, but a *transitive* one, working out through a prerequisite chain rather than a course's own direct restrictions, which is a step further than the direct-restriction-awareness fix already shipped for `ElectiveFiller`/`_select_electives` covers. The CLI defaults to today's actual month to guess a starting semester, so this is why the exact set of "broken" double majors can look different depending on what day you run it.

Fixed: `_select_electives` now computes each pool candidate's unavoidable (non-OR) prerequisite closure and checks it for restriction conflicts too, not just the candidate's own restrictions field, and also checks against the other major's direct requirements (previously invisible to pool selection entirely). Regression test: `test_select_electives_skips_course_whose_forced_prereq_conflicts` in `tests/test_integration.py`.

Two more cases surfaced verifying the fix, both data-level, not scheduler bugs, confirmed by reproducing each as a *single* major with no double-major involved, and against the unmodified pre-fix code:

- **Mathematics – Bachelor of Science**, resolved: directly requires `160101` and `160102`, and its own L200 pool has exactly 4 candidates for a 60cr target (all 4 mandatory), one of which (`160212`) was recorded with a prerequisite requiring `160105`, which mutually restricts both `160101` and `160102`. Live-verified: `160212`'s real prerequisite is "one of (...) and one of (...)" (see corrections list above), not the flat AND that was stored - correcting the stored data resolves this without any scheduler change.
- **Animal Science – Master of Science** directly requires both `119728` and `162760`, which mutually restrict each other. Same shape: two hard requirements that cannot both be satisfied. Given the code-prefix mismatch (119xxx vs 162xxx), this has the same signature as the AND/OR scraper confusion already documented elsewhere in this file (plausibly "one of 119728 or 162760" scraped as "both required") but unverified against the live page.

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

**2. Required courses that cannot, by themselves, reach the credit needed to unlock a later required course (~6 of 40 sampled, e.g. Te Reo Māori, Educational Psychology, Media Studies, Linguistics, Property).** `_repair_level_progression`'s swap/drop mechanism only ever touches *elective pool* selections. Required (non-pool) courses are always kept, by design, since dropping an actually-required course would silently produce an incomplete degree. When the required-course list itself doesn't add up to 45cr at the level below a later required course, there's nothing the scheduler can rearrange; the major's required-course list, as scraped, is genuinely incomplete for a DIS student following only what's listed as required. This is the same root cause already documented for Chinese, Bachelor of Arts (below), confirmed, not a new bug, just newly visible because nothing previously checked for it. English, Bachelor of Arts has the identical shape outside the original sample: `139139` plus a 15cr L200 pool cap out at 30cr L200, short of the 45cr its 45cr L300 pool (`139305` etc.) needs.

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


## Known Open Items

`scripts/audit_prereq_contradictions.py` finds courses whose own stored
prerequisite requires two mutually-restricting codes in the same AND
clause - always a scraper error (a "one of A, B, C" list parsed as a flat
AND), never a real requirement. Run it after every re-scrape. It's how
160212 and 123201 were confirmed this pass; running it across the whole
dataset (not just the two courses a broken major happened to point at)
found 6 more, not yet live-verified:

- `241305` / `241304` (both require `241301` AND `241302`, which restrict each other)
- `286321` / `117243` / `117226` (all require `117153` AND `117155`, which restrict each other)
- `120303` (requires `120201` AND `120219`, which restrict each other)

Full history is in CHANGELOG.md. This section is the current, still-open list only.

Full history of what was found and fixed, and when, is in CHANGELOG.md.
This section is the current, still-open list only.

**Double-major semester-timing sensitivity.** Not investigated in detail.

**10 majors in the D/DIS sweep fail with a generic "No schedulable
courses remain" error, not individually traced.** Two spot-checked:
- `234338` (Sport and Exercise Practicum) has a 6-course flat AND
  prerequisite (`234214`, `234215`, `234236`, `234243`, `152237`,
  `152238`, all L200, all offered D/DIS). Six concurrent L200
  prerequisites for one course has the same shape as the comma-parser
  bug ("one of A, B, C, D, E, F" misread as "all of"), but none of the
  six restrict each other in the current dataset, so the
  mutual-restriction cross-check that found other instances of this bug
  didn't catch it. Worth checking against the live page first.
- `256304` (Positive Learning Environments, requires `256201`) and
  `233209` (Earth's Critical Resources, requires `233105`) each have a
  single valid D/DIS prerequisite with no prerequisite of its own - not
  a data-parsing issue, looks like a scheduling-horizon limitation
  instead. Not investigated further.

**"One of"/"any of" detection in `prerequisite_scraper.py` only fires on
those two exact phrases.** Other wording for the same meaning ("Choice
of X, Y, Z", "Either X, Y or Z", "Select one of X, Y") would still fall
back to comma-as-AND, reproducing the original bug under different
phrasing. Not fixed without a live example - guessing at phrasing
variants risks introducing a wrong pattern. Worth grepping a dry-run's
output for "of " near comma-separated code lists that didn't get OR
treatment.

**Parenthesized "one of" lists may exist beyond the one confirmed
course.** `123305`'s page uses a bare parenthesized comma list with no
explicit "or"s; the regex now handles that exact shape. Unknown whether
other courses use the same phrasing or something still different. Worth
grepping a dry-run's debug output for `"of ("`.

**Whether the Oxford-comma tokenizer bug (comma directly followed by a
literal "and"/"or") already corrupted anything in the current
`courses.json`.** The fix only affects future scrapes. Worth checking
during the next re-scrape's dry-run: any course whose prerequisite text
contains ", and" or ", or" should parse to the expected number of
top-level AND args, not one.

**Mechanism behind stale content being served under sustained request
volume is not independently confirmed.** CDN edge caching under origin
load is the leading theory, consistent with every observation, but
unverified against Massey's actual infrastructure. The regression-guard
fix (`_is_suspicious_regression`) detects the symptom rather than
depending on the cause, so this doesn't block anything - it's just
genuinely unknown.
