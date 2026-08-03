# Data Quality

What the planner's data covers, what's confirmed correct, what's confirmed wrong, and what's unverified. If you're deciding whether to trust a plan this tool generates, read this first.

---

## Dataset overview

| File | Records | Source |
|---|---|---|
| `datasets/courses.json` | 2,766 courses | Massey Swiftype API + page scraping |
| `datasets/majors.json` | 380 majors | Massey Swiftype API + requirement pages |
| `datasets/qualifications.json` | 176 qualifications | Massey Swiftype API |
| `datasets/minors.json` | 39 minors | Pattern-inferred from `courses.json` (not yet scraped from live pages) |

Course `description` fields are auto-generated boilerplate (level/credits/campus summary), not Massey's real course description. The ↗ link on any course card goes to the real page.

---

## Qualification credit totals

`qualifications.json`'s `length` field comes from Massey's `qual_length` field - a coarse duration category, not a precise credit total. `DegreeProfile` (`rules/degree_rules.py`) derives `total_credits = length * 120`, which is wrong for any qualification whose real total isn't a whole number of years.

All 41 Level-9, `length=2` qualifications have been checked against their own official regulations page. **32 of 41 (78%) were wrong** and are now corrected via a cited override table (`_VERIFIED_QUALIFICATION_LENGTH_FIXES` in `repair_dataset.py`), baked into the shipped dataset and covered by tests. 9 are confirmed correct at 240cr. The remaining 6 Level-9 qualifications (already `length=1`) are unverified but plausible.

**Open, architectural gap:** several qualifications' real credit total depends on the individual student's prior study (e.g. entering with vs without Honours) - Massey states this explicitly for master's degrees generally, and MSc has a documented 180cr/240cr split. `DegreeProfile` has no concept of this on its own, and the planner has no way to *detect* which pathway applies to a given student. A manual `credits_override` parameter (`/api/plan`, `--credits-override`, and a `GET /api/majors/pathway-notice` endpoint that surfaces the ambiguity) lets a student who knows their own total plan against it correctly - but this only covers qualifications named in `_QUALIFICATIONS_WITH_ALTERNATE_TOTALS` (currently just MSc), and it's still on the student to know and enter the right number. A general solution needs a real prior-study input the planner can reason about on its own, not another data fix.

Free-elective pool sizes in `majors.json` are derived from each qualification's total at build time. When 48 of the 51 affected majors had a stale, pre-fix total baked in as an absolute number, those pool sizes were wrong too - fixed as part of the same pass (`fix_stale_free_elective_pool_sizes`, Pass 5 of the repair pipeline). 3 majors (Ecology and Conservation – MSc, Occupational Health and Safety – MHS, Māori Health – MHS) needed the correlated-pathway fix below instead of the automatic correction, since their non-open pools already exceeded the corrected total on their own.

---

## Correlated-pathway majors (Part One / Part Two choice)

Several majors offer a genuine choice of pathway (e.g. coursework vs research, or thesis size), where Part One's credit split depends on which Part Two option is taken. The schema already supports this correctly - `ANY_OF` nodes whose children are themselves `ALL_OF` nodes express a correlated choice with no code changes, and `collect_elective_nodes` already resolves exactly one branch as a unit. The gap was in the data, not the engine.

**Fixed, live-verified, and tested** (6 of 7 known instances):
- **Geography** - 3-way: Coursework (Part One 120cr + Part Two 60cr Research Report), Research/90 (90cr + 90cr thesis), Research/60 (60cr + 120cr thesis), all drawing Part One from a shared 6-course pool.
- **Sociology** - same 3-way shape; Part One has a 60cr compulsory pair common to all three plus a variable subject component.
- **Ecology and Conservation – MSc** - 2-way: 60cr subject + 90cr thesis, or 30cr subject + 120cr thesis, plus a 30cr compulsory research-methods pool common to both.
- **Occupational Health and Safety – MHS** - same 2-way shape, plus one compulsory course (`251731`).
- **Māori Health – MHS** - 3-way (90/60/30cr subject against 60/90/120cr thesis), plus one compulsory course (`150714`), which was missing from the previously scraped data entirely, not just mis-sized.
- **Earth Science – MSc** - 2-way, with a 15cr compulsory research-methods pool (one of three mutually-restricted options) common to both pathways.

English – MA was already correctly modelled (two genuine `CHOOSE_CREDITS` pools) and needed no change.

**Open:** TESOL – Master of Applied Linguistics has the same correlated-pathway duplication (two pools sharing an identical candidate list) plus a separate over-specification that persists even once the duplication is resolved. Needs the same live-verify-and-re-encode treatment as above for the pathway half, and the re-scraping work described below for the over-specification half.

**Unverified:** whether Education and roughly 39 other majors sharing the same Master of Arts `(60cr, 120cr)` shape have the same Part One problem. `scripts/audit_pool_overlap.py` finds candidates dataset-wide - do not bulk-apply a fix from its output alone, since a legitimately-both-required shared pool looks identical to a mis-encoded either/or from the data alone; each candidate needs its own live-page check.

**Education – MA specifically:** live-verified Part Two codes are `267860` (Coursework, 60cr), `267871`/`267872` (Thesis 120cr), `267881`/`267882` (Thesis 90cr) - the previously stored `267861`/`267875` belong to a different qualification (PMEDC, Master of Education) and are wrong. Constructing the coursework pathway as Massey's own page describes it (120cr Part One + 60cr Part Two = 180cr) produces 195cr in practice, because `267860` has its own ~15cr prerequisite that the page's summary doesn't visibly account for. Not shipped - the discrepancy is unresolved and guessing at it risks repeating the same category of error already found and corrected elsewhere in this dataset. `test_education_ma_still_has_wrong_part_two_course_codes` pins the current state as `xfail(strict=True)`.

---

## Over-specified majors

**~36 majors (9.5%)** have scraped data listing more required-looking courses (or required courses + every pool's own stated minimum) than the qualification's credit target allows for - e.g. a 120cr diploma whose data lists 165cr of compulsory-looking codes. Concentrated in postgraduate Psychology, Education, and Māori Studies. Root cause: source data flattening several alternative specialisation tracks into one list, not the degree genuinely requiring more credits than it awards.

The planner will cap the *droppable* portion of a required-course list to fit the credit budget, but never drops a course its own validation tree checks as required - even if that produces a plan over the credit target. An over-target plan is a visible failure; a plan silently missing a required course is not, so the tool is deliberately biased toward the former. For majors in this category, the only real fix is re-scraping the requirement page and modelling the alternative tracks as genuine choice structures - not a scheduler change.

Known specific instances: Human Resource Management – MBS, Economics – MA (required courses + pool minimums together exceed the total, even though no single list does on its own).

---

## Prerequisite coverage

| Status | L200–400, undergrad | L200+, all levels |
|---|---|---|
| Prerequisite data recorded | 770 (66.3%) | 867 (36.4%) |
| No prerequisite data recorded | 391 (33.7%) | 1,512 (63.6%) |

"No prerequisite data recorded" means the scraper found nothing for that course - it does not mean the course has no prerequisite. Treat it as unverified. Many postgrad/thesis courses genuinely have no prerequisite beyond programme admission; that's not separated out from genuine gaps, so the UI flags both the same way.

**UI indicator** - a dot next to each course code: green (recorded, satisfied by this point in the plan), amber (recorded, not yet satisfied), blue (no data recorded, unverified), no dot (L100, or confirmed to genuinely have none). The course drawer's Prerequisites section links to the real Massey page for anything unverified.

**Known specific corrections**, live-verified and applied via `_VERIFIED_PREREQ_FIXES` in `repair_dataset.py` (source-cited there, regression-tested):

- `159251` - no prerequisite recorded; actually requires `159234`
- `159302` - recorded as `159234` AND `159201`; actually `159201` OR `159234`
- `159356` - missing `159352`
- `159342` - recorded as AND; actually OR (`159201` or `159234`)
- `159352` - wrong courses entirely; actually (`159100` or `159101`) and `158258`
- `159361` - missing `159235`
- `159336` - recorded as AND; actually OR (`159234` or `159235`)
- `158222` - wrong courses entirely; approximated as (`159100` or `159101`) and one of `160101`/`160102`/`161111`/`161122` (real requirement references a "1611xx" prefix pattern the schema can't express - see limitation below)
- `159333` - real requirement is "three of 1592xx, 1582xx or 2972xx" (choose-3-of-pool); approximated as requiring `159201` alone
- `161222` - no prerequisite recorded; real requirement "1611xx", approximated as OR of `161101`/`161111`/`161122`/`161140`
- `161250` - recorded as requiring `161111` specifically; real requirement "1611xx or 297101"
- `161251` - same issue as `161250`, same fix
- `161380` - no prerequisite recorded; real requirement "two 1613xx courses" (choose-2), approximated as `161304` alone. Graduate-Diploma-only, no current DIS offering, so the approximation has no practical effect today.
- `160212` - recorded as a flat AND of all 10 codes across both clauses; real requirement is two independent choose-one clauses. This was the direct cause of Mathematics – BSc appearing self-contradictory.
- `123201` - same flat-AND pattern; real requirement "one of (123102, 123105, 124104, 123172) and one of (160101, 160102, 160105, 160132, 160133)". Was the direct cause of Chemistry – BSc failing to generate.
- `117226`, `286321` - real requirement "one of 117152, 117153, 117155 or 194101"
- `117243` - real requirement "one of 117153, 117155 or 194101"
- `120303` - real requirement "one of (120201, 120218, 120219, 196205, 196207, 203210)"
- `117201`, `117202` - same flat-AND-of-a-choice pattern
- `123305` - nested case: "one of these 6 sciences and one of these 4 sustainability courses", was stored as all 10 required
- `289250`, `289350` - same pattern
- `241304`, `241305` - checked and confirmed **not** the AND/OR bug: both pages genuinely say "241301 and 241302 or appraisal required," a real AND plus an alternative the schema can't express. Left unchanged.

**Schema limitation:** the prerequisite tree only supports AND/OR over fixed course codes. It cannot express "choose N of M" or prefix-pattern alternatives (e.g. "any 1611xx course"). Courses with this kind of requirement are approximated by expanding to the known matching codes. Restrictions/corequisites are flat code lists with the same limitation one level simpler - "one of X, Y, Z" collapses to `[X, Y, Z]` with the choice meaning lost.

**A stored fix does not survive re-scraping on its own** unless the live parser now also handles that page's phrasing (in which case reapplying the override is a harmless no-op). Four entries (`161222`, `161250`, `161251`, `161380`) are a genuine exception: the live page has no literal course-code list for these ("1611xx", "two 1613xx courses"), so a fresh scrape will always return fewer codes than the deliberately-expanded override. These four trip the regression guard (`_is_suspicious_regression`) and are correctly skipped on every re-scrape, by design - they need to stay as permanent manual entries until the schema supports choose-N-of-M.

### Refreshing prerequisite, restriction, and corequisite data (requires network access to massey.ac.nz)

```bash
# Step 1 - connectivity check
python scripts/test_prereq_scraper.py

# Step 2 - full refresh, ~2-3 hours for all 2,766 courses
python -m coursemap.ingestion.refresh_prerequisites

# Only re-scrape courses with no prerequisite data (does not cover restrictions/corequisites,
# since an empty list there is indistinguishable from "genuinely has none" once scraped)
python -m coursemap.ingestion.refresh_prerequisites --only-missing

# Test with a subset
python -m coursemap.ingestion.refresh_prerequisites --limit 50

# Reduce concurrency if rate-limited
python -m coursemap.ingestion.refresh_prerequisites --concurrency 5
```

---

## Restrictions and corequisites

Both fields are populated as of the current dataset (restrictions 75.6% empty, corequisites 93.6% empty - expected, since most courses genuinely have neither). `coursemap/planner/generator.py`'s restriction check was always correct but was silently unreachable for every plan ever generated until this data existed.

`ElectiveFiller` and `search.py`'s `_select_electives` now exclude a candidate if its restrictions overlap anything already in the plan (checked in both directions, since Massey's own pages don't always cross-reference), and track restrictions introduced within the same fill pass so two mutually-restricted candidates ranked in the same batch can't both be picked.

---

## Double majors

All double-major generation failures traced to three distinct causes, all now understood:

1. **Mutually-restricted course variants hard-required per major** (e.g. Computer Science requiring `247112` where Mathematics requires the mutually-restricted `247113`) - fixed by converting the hardcoded single-course requirement into a shared `CHOOSE_CREDITS` pool of known variants across 17 affected majors, so any one satisfies the requirement.
2. **Pool credit accounting didn't recognise an overlap between a pool option and another major's direct requirement** - fixed in `_select_electives`; the overlapping code stays in the pool's candidate list (correctly counted) rather than being stripped and re-filled with a second, possibly-conflicting course.
3. **No shortfall-tolerant discovery pass for double majors** (single-major generation tolerates a temporary shortfall during discovery and lets `ElectiveFiller` close it; double-major generation didn't) - fixed via `deferred_codes` on `PlanGenerator` plus extending the existing shortfall-tolerance check to cover a deferred required course, not just a short pool.

**Semester-sensitivity:** two more major-pair combinations fail only for one of the two starting semesters (Computer Science + Statistics fails S2, works S1; Computer Science + Data Science is the reverse) - caused by a transitive prerequisite-chain conflict, not a direct restriction. Fixed by having `_select_electives` compute each candidate's non-OR prerequisite closure and check that for restriction conflicts too, plus checking against the other major's direct requirements.

**Not investigated in detail:** general double-major semester-timing sensitivity beyond the two pairs above.

---

## 45-credit level-progression rule

Massey's General Regulations require 45cr passed at 100-level before enrolling in a 200-level course, and 45cr at 200-level before 300-level - independent of any individual course's own prerequisite. Applies to undergraduate degrees/diplomas/certificates; not to postgraduate qualifications (gated by programme admission instead).

Enforced in `generator.py` during scheduling and both rebalancing passes, gated on qualification level.

A sample of 40 undergraduate majors found the following breakdown once checked with the rule enforced:
- **Genuinely fine (8 of 40):** produce a fully valid plan with no issue.
- **Pre-existing failures unrelated to this rule (~12 of 40):** e.g. a required Summer-School-only course under a `--no-summer` plan, or majors with no DIS offering at all.
- **Required-course list itself doesn't add up to 45cr at the level below (~6 of 40)** - e.g. English – BA: `139139` plus a 15cr L200 pool caps at 30cr L200, short of what its 45cr L300 pool needs. Nothing to rearrange; the required-course list as scraped is genuinely incomplete for a DIS-only student.
- **Named elective pool alone can't supply enough lower-level credit to justify its own higher-level selections (~13 of 40)** - e.g. Accountancy, Spanish, Japanese, Psychology. `_repair_level_progression` swaps within the same pool where possible, and drops an unschedulable higher-level selection to avoid deadlocking generation when no swap exists - but the resulting shortfall can only be closed by courses from that same named pool, since `DegreeValidator`'s pool check only counts a pool's own listed codes. Generic filler cannot satisfy it.

---

## Level distribution (max 165cr at 100-level, min 75cr at 300-level)

Separate from the progression rule above. Verified against live regulations: BSc, BA, BCom, and BInfoSci all specify "not more than 165 credits at 100-level" and "at least 75 at 300-level" (Bachelor of Business is 180cr, not 165 - see the comment on `_DEGREE_PROFILES` in `degree_rules.py`).

`DegreeProfile` computes the correct numbers, but `build_degree_tree` does not yet emit the corresponding `MaxLevelCreditsRequirement`/`MinLevelCreditsRequirement` nodes - the constraint is not enforced on any plan. `test_build_degree_tree_does_not_yet_emit_level_constraints` pins this as a known gap.

What is shipped: `PlannerService._level_distribution_state` and `ElectiveFiller`'s `level_credit_limits`/`level_floor_priority` mechanism steer filler selection toward a sensible level distribution even without hard enforcement, and are tested on their own terms.

What's blocking hard enforcement: `search.py`'s `_select_electives` fully satisfies each elective pool's own nominal credit target independently of any shared budget - when a major's own pool and an injected filler pool are both present, their targets simply add rather than sharing one combined budget. `TotalCreditsRequirement` uses `>=`, so this overshoot currently passes validation silently; a per-level cap would be the first check strict enough to catch it. Fixing this needs `_select_electives`'s pool-budget accounting reworked to share one running budget - `_select_electives` is a ~250-line function used by every generation path, so this needs its own dedicated pass rather than a fix bundled into re-enabling the level-distribution nodes.

---

## Offering data gaps

**323 courses** (marked `?` in the UI) are required in a major but have no confirmed 2026 offering data - given an inferred offering based on other courses in the same subject prefix, or whether the title suggests a flexible "Special Topic"/thesis course. Refresh with:

```bash
python -m coursemap.ingestion.build_dataset
```

---

## Majors with weak data

**4 majors** have no specific required course codes at all (entire degree modelled as free electives): Biological Sciences – Postgraduate Diploma in Science and Technology; Expressive Arts and Media Studies – Bachelor of Communication; Without Specialisation – Graduate Certificate in Arts; Without Specialisation – Graduate Diploma in Arts.

**89 majors** have >200cr of free-elective gap - the requirement tree only specifies a subset of the degree, and the planner fills the rest automatically without that fill being based on real programme regulations.

---

## Minors

The 39 minors in `datasets/minors.json` are pattern-inferred from the course dataset, not scraped from or verified against individual Massey minor pages (each entry's own `note` field says so explicitly). `scripts/scrape_minors.py` exists to do a real per-minor page scrape instead, but hasn't been run against the shipped data yet - every entry is still `data_quality: "inferred"`, not `"scraped"`. Course code lists may not match the current handbook year; level splits are typical but may vary by programme. Treat with the same caution as unverified prerequisite data.

---

## Re-scraping the full dataset

Requires the Massey website to be reachable (blocked in some CI/server environments).

```bash
# Full re-scrape (several hours)
python -m coursemap.ingestion.build_dataset

# Faster - courses only, not majors/quals
python -m coursemap.ingestion.refresh_prerequisites

# After any re-scrape
python -m coursemap.ingestion.repair_dataset
```

Restart the server afterward - the dataset is cached at startup.

---

## Systemic-check tooling

`scripts/audit_prereq_contradictions.py` finds courses whose own stored prerequisite requires two mutually-restricting codes in the same AND clause - almost always a scraper error (a "one of A, B, C" list parsed as a flat AND). One confirmed exception: `241304`/`241305`, where the AND is genuinely correct (see the prerequisite corrections list above). Run after every re-scrape.

`scripts/audit_pool_overlap.py` finds majors where two supposedly-both-required parts of a requirement tree share course codes - the signature of a mis-encoded either/or choice. A legitimately-both-required shared pool looks identical from the data alone, so do not bulk-apply a fix from its output; verify each candidate against a live page first.

---

## Open items

- Qualification pathway choice (prior-study-dependent credit totals): a manual `credits_override` exists for MSc, but there's still no general, planner-detected solution - see "Qualification credit totals" above.
- TESOL – Master of Applied Linguistics correlated pathway + over-specification, unresolved.
- ~39 further Master of Arts specialisations sharing Education/Geography's Part One shape, unverified.
- Education – MA Part Two: 15cr prerequisite discrepancy against the qualification's own stated total, unresolved (`xfail`, see above).
- Human Resource Management – MBS, Economics – MA and the broader ~36-major over-specified-required-list category need re-scraping and remodelling as genuine choice structures, not a scheduler fix.
- Level-distribution hard enforcement blocked on `_select_electives` pool-budget sharing (see above).
- `search.py` is ~1,960 lines and due for a split by concern.
- Massey-specific assumptions run through the domain/rules/scraper layers; multi-university support needs an abstraction pass, not a toggle.
- Prerequisite "one of"/"any of" detection only fires on those two exact phrases - other wording (e.g. "Choice of X, Y, Z") falls back to comma-as-AND and would reproduce the original bug under different wording. Not fixed without a confirmed live example.
- Whether the current dataset has any course whose prerequisite text contains a literal ", and" or ", or" that a since-fixed tokenizer bug corrupted is unconfirmed - the fix only affects future scrapes; worth checking on the next re-scrape's dry run.
- Animal Science – MSc still cannot generate a D/DIS plan even with its data corrected - a genuine greedy-ordering limitation in `_select_electives` (it doesn't backtrack once an earlier pick blocks a later one), not a data or restriction bug.
