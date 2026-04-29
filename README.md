# coursemap v1.0

**Massey University degree planner** - generate semester-by-semester study plans for any Massey major or double major, with prerequisite scheduling, auto-fill of free electives, and degree validation.

## Quick start

```bash
pip install -e .
python -m coursemap.api.server
# Open http://localhost:8080
```

## What's in v1.0

- **93/111 undergrad bachelor's majors** produce exactly 360cr plans (18 require campus-specific offerings)
- **All double majors** reach the degree target with shared-course savings displayed
- **Complete UI redesign** - dark theme, course drawer, browse modal, share links, saved plans, mobile layout
- **6 scheduler bugs fixed** - SS deadlock, horizon counting, pool overlap, elective fill scope, TotalCredits gate, filler tolerance

## Architecture

```
coursemap/
  api/          FastAPI server + ui.html
  domain/       Course, Offering, Prerequisite, Requirement dataclasses
  ingestion/    Dataset loaders + scrapers
  optimisation/ PlanSearch (greedy topological scheduler)
  planner/      PlanGenerator (semester-by-semester engine)
  rules/        Degree tree builder (360cr, TotalCredits constraints)
  services/     PlannerService (orchestration + elective fill)
  validation/   Plan validator against requirement tree
datasets/
  courses.json    2,766 courses with offerings
  majors.json     380 majors with requirement trees
  qualifications.json
  specialisations.json
```

## Known limitations

- Course **descriptions** not yet scraped (shows "No description" in UI)
- Prerequisite data uses flat-list scraper; new HTML-aware scraper exists but not yet run
- 3 majors (English BA, Linguistics BComm, Expressive Arts BComm) have discontinued courses in required pools - cannot be solved
- Offerings are 2026 only; planner treats semester type (S1/S2) as repeating annually

---

# coursemap

CLI tool that generates a valid semester-by-semester degree plan for any of Massey University's 380 majors. Solves prerequisite ordering, delivery-mode filtering, elective selection, and credit constraints as a constrained DAG scheduling problem over a live dataset of 2,766 courses.

```
$ coursemap plan --major "Computer Science" --auto-fill

Degree plan: Computer Science – Bachelor of Science
Starting:    2026  |  Delivery: D/DIS

2026 S1  (60 credits)
   158100  15cr  Information Technology Principles
   159101  15cr  Applied Programming
   159333  15cr  Programming Project
   161111  15cr  Applied Statistics

2026 S2  (45 credits)
   158120  15cr  Web-based IT Fundamentals
   159102  15cr  Computer Science and Programming
   159223  15cr  Artificial Intelligence Methods

2027 S1  (60 credits)
   159201  15cr  Algorithms and Data Structures
   159224  15cr  Methods in Machine Learning
   159234  15cr  Object-Oriented Programming
   159261  15cr  Games Programming

2027 S2  (60 credits)
   159235  15cr  Programming for Computer Graphics
   159236  15cr  Embedded Programming
   159251  15cr  Software Engineering Design and Construction
   159272  15cr  Programming Language Paradigms

2028 S1  (60 credits)
   159341  15cr  Programming Languages, Algorithms and Concurr...
   159342  15cr  Operating Systems and Networks
   159352  15cr  Advanced Web Development
   247112  15cr  Science and Sustainability for ICT

2028 S2  (45 credits)
   159302  15cr  Artificial Intelligence
   159336  15cr  Mobile Application Development
   159356  15cr  Software Engineering Capstone Project

Summary
  Semesters planned : 6
  Credits planned   : 360
  Credits total     : 360
  Degree target     : 360cr  (auto-filled)

Major requirements: satisfied

Free electives: 150cr gap auto-filled with 10 subject-area course(s) (150cr)
```

## Motivation

Massey's course catalogue has 2,766 courses across 380 majors. Each course has prerequisites, semester availability, campus, and delivery mode constraints. Planning a degree manually means cross-referencing all of that across 6–10 semesters.

This tool models the problem as a DAG scheduling problem: build a prerequisite graph, derive each degree's constraint tree from qualification metadata, run a greedy topological sort with credit-cap constraints, and validate the result against that tree.

**Coverage:** 340 of 380 majors produce valid distance plans. The remaining 40 are studio/performance programmes with no published distance offerings (they work with `--campus M --mode INT`).

## Install

Python 3.11+.

```bash
git clone https://github.com/bonniemcconnell/coursemap
cd coursemap
pip install -e .
```

Datasets are bundled. No network access needed to run the planner.

## Usage

```bash
# Browse available majors (word-overlap matching: 'comp sci' finds Computer Science)
coursemap majors --search "comp sci"

# Full-time distance plan - auto-resolves to BSc when unambiguous
coursemap plan --major "Computer Science"

# Auto-fill the free-elective gap with subject-area courses (full 360cr plan)
coursemap plan --major "Computer Science" --auto-fill

# Double major - merges both requirement trees, deduplicates shared courses
coursemap plan --major "Computer Science" --double-major "Mathematics"
coursemap plan --major "Computer Science" --double-major "Mathematics" --auto-fill

# Mark courses already completed
coursemap plan --major "Computer Science" --completed 159101,159102

# Credit recognition from prior learning at another institution
coursemap plan --major "Computer Science" --transfer-credits 60

# Half-time load (30cr/sem), skip Summer School
coursemap plan --major "English" --max-credits 30 --no-summer

# On-campus plan (Manawatu, internal delivery)
coursemap plan --major "Ecology and Conservation" --campus M --mode INT

# Prefer specific electives when there is a choice
coursemap plan --major "Statistics" --prefer 161307,161308

# Cap at two courses per semester
coursemap plan --major "Accountancy" --max-per-semester 2

# Export as shareable HTML (self-contained, print-ready)
coursemap plan --major "Computer Science" --auto-fill --format html

# Export JSON only - no terminal output (pipeline/scripting use)
coursemap plan --major "Computer Science" --format json --output plan.json

# Show why courses were excluded from this plan
coursemap plan --major "Computer Science" --campus M --mode INT --explain

# Show scheduler diagnostics
coursemap plan --major "Computer Science" --debug

# Browse courses with delivery info
coursemap courses --search "machine learning"
coursemap courses --search "algorithms" --mode DIS
coursemap courses --level 300 --campus M

# Dataset integrity check
coursemap validate
coursemap validate --quiet   # errors only
```

### plan flags

| Flag | Default | Description |
|---|---|---|
| `--major NAME` | required | Partial/abbreviated name. Smart disambiguation resolves to BSc/BA when unambiguous. Run `coursemap majors` to browse. |
| `--double-major NAME` | none | Second major for a combined plan. Courses shared between majors are scheduled once. |
| `--start-year YEAR` | 2026 | First calendar year of study. |
| `--max-credits N` | 60 | Credit cap per semester (60 = full-time, 30 = half-time). |
| `--max-per-semester N` | none | Course count cap per semester. |
| `--campus CODE` | D | D (distance), M (Manawatu), A (Albany), W (Wellington). |
| `--mode CODE` | DIS | DIS (distance), INT (internal), BLK (block). |
| `--completed CODES` | none | Comma-separated course codes already completed. |
| `--transfer-credits N` | 0 | Unspecified credit recognition from prior learning at another institution. |
| `--prefer CODES` | none | Comma-separated elective codes to prioritise. |
| `--no-summer` | off | Skip Summer School (SS) semesters entirely. |
| `--auto-fill` | off | Auto-select subject-area electives to fill the free-elective gap, producing a complete degree plan. |
| `--explain` | off | Show which courses were excluded and why (no offerings / wrong campus+mode). |
| `--format` | text | Output format: `text` (default), `html` (self-contained file), `json` (file only, no terminal output). |
| `--output FILE` | plan.json / plan.html | Output file path. |
| `--debug` | off | Show scheduler diagnostics (rejections, rebalance moves). |

### courses flags

| Flag | Default | Description |
|---|---|---|
| `--search QUERY` | none | Filter by title (word-overlap, e.g. "machine learning"). |
| `--level N` | none | Filter by level (100, 200, 300, …). |
| `--campus CODE` | none | Show only courses with an offering at this campus. |
| `--mode CODE` | none | Show only courses in this delivery mode. |
| `--show-inactive` | off | Include courses with no current offerings (retired). |

Offering labels show delivery split: `[DIS:S1, INT:S1/S2]` means distance in S1, internal in both semesters.

### validate flags

| Flag | Default | Description |
|---|---|---|
| `--quiet` | off | Suppress warnings; only show errors. |
| `--all` | off | Show all warnings (default: first 20). |

## How it works

### Prerequisite graph and scheduling

Course prerequisites form a directed acyclic graph. `planner/generator.py` runs a greedy topological sort: each semester slot, collect all courses whose prerequisites are satisfied and whose offering matches the configured campus and delivery mode, then fill up to the credit cap in code order.

Any prerequisite code not in the current working set is treated as pre-satisfied. This handles cross-programme prerequisites from prior degrees and courses outside the major's scope.

After the greedy pass, four rebalancing passes run:
1. **Pull-forward:** if the final semester is underfilled (<30cr), eligible courses are moved forward from earlier semesters.
2. **Drop empty:** semester slots emptied by pass 1 are removed.
3. **Merge:** if the final and penultimate semesters share the same type and fit within the cap combined, they merge.
4. **Equalise:** underfull mid-plan semesters pull courses forward from later same-type semesters to smooth load imbalances.

### Major name resolution

Four-tier matching, applied in order:
1. **Exact** case-insensitive match.
2. **Substring** match - `"computer science – bsc"` finds the full name.
3. **Smart disambiguation** - if multiple matches exist but the query has no degree-type qualifier (`bachelor`, `master`, etc.), postgrad options are filtered first, then a preference order (BSc > BA > BBus > BHSc > BIS) resolves a single result. `"Computer Science"` → `Computer Science – Bachelor of Science`.
4. **Word-overlap** - every query word must appear as a substring of some token in the name, so `comp sci` matches `Computer Science`.

Unresolved queries fall back to difflib sequence similarity for typo suggestions.

### Free-elective gap

The gap is calculated as `degree_total − (required_credits + pool_targets)`, where pool targets are the *minimum* credits to satisfy each elective pool (not the sum of all pool alternatives). For CS BSc: 90cr required + 60cr pool 1 target + 60cr pool 2 target = 210cr, gap = 360 − 210 = 150cr.

`--auto-fill` fills this gap by selecting subject-area courses (same code-prefix, sorted by level) and re-running the scheduler with the augmented working set. `--transfer-credits N` counts N credits of prior learning toward the gap without requiring specific course codes.

### Double major

`--double-major NAME` merges both requirement trees into `ALL_OF(first_req, second_req)` and schedules a single unified working set. Courses shared between the two majors appear once in the schedule. The plan output reports how many shared courses were found and how many credits of overlap were saved. Both requirement trees are validated independently against the combined plan.

### Requirement trees

Every degree is represented as a tree of `RequirementNode` objects derived at runtime from `qualifications.json` (NZQF level and duration → total credit target) and `majors.json` (required courses and elective pools):

```
ALL_OF
  TOTAL_CREDITS(360)           ← only present when dataset covers full degree
  ALL_OF                       ← major-specific requirements
    COURSE(147102)
    COURSE(147204)
    ...
    CHOOSE_CREDITS(120)        ← elective pool: pick 120cr from these
      [147202, 147302, ...]
```

No hardcoded degree configuration file. All 380 majors derive their trees from the same two JSON sources.

### Elective selection

For each `CHOOSE_CREDITS` pool, the planner picks the minimum number of courses meeting the credit target, sorted by: (1) student preference (`--prefer`), (2) earliest semester offered, (3) level, (4) code. O(M log M) per pool.

### JSON output schema

`plan.json` contains a `meta` block and a `semesters` array:

```json
{
  "meta": {
    "major": "Computer Science – Bachelor of Science",
    "campus": "D",
    "mode": "DIS",
    "start_year": 2026,
    "credits_planned": 360,
    "credits_prior": 0,
    "credits_transfer": 0,
    "credits_total": 360,
    "degree_target": 360,
    "free_elective_gap": 150,
    "auto_filled_codes": ["159223", "159224", ...]
  },
  "semesters": [
    {
      "year": 2026,
      "semester": "S1",
      "credits": 60,
      "courses": [
        {"code": "159101", "title": "Applied Programming", "credits": 15},
        ...
      ]
    }
  ]
}
```

For double-major plans, `meta` also contains a `double_major` block with `first`, `second`, `shared_codes`, and `saved_credits`.

### Prerequisite data quality

The dataset uses the original flat-list format from an older scraper (every six-digit code visible on the page). Three filters clean it at load time:

1. **Admission noise.** Codes `627739` (University Entrance) and `219206` (NZQF Level 3) stripped unconditionally.
2. **Plausibility filter.** Keep only same-subject prerequisites at a strictly lower level or earlier code.
3. **Phantom stripping.** Any prerequisite code that doesn't exist in the catalogue is removed. After this step, `coursemap validate` reports zero prerequisite-code warnings.

`ingestion/prerequisite_scraper.py` contains a new HTML-aware scraper that parses the prerequisites section specifically and builds structured AND/OR trees. Running it restores cross-subject prerequisites. Massey's CDN requires network access to re-scrape.

Both `courses.json` and `majors.json` are schema-validated at load time; malformed datasets produce a clear error message rather than a cryptic `KeyError`.

## Architecture

```
coursemap/
  cli/           Argument parsing, terminal output, HTML/JSON export.
  services/      PlannerService: major resolution, degree tree construction,
                 generate_best_plan / generate_filled_plan / generate_double_major_plan.
  rules/         DegreeProfile lookup; requirement tree construction from qual metadata.
  planner/       PlanGenerator: greedy topological scheduler with 4-pass rebalancing.
  optimisation/  PlanSearch: elective selection and plan scoring.
  validation/    DegreeValidator: recursive requirement tree checking.
                 DatasetValidator: prerequisite cycles, offering validity, major code refs.
  domain/        Pure data types (Course, Offering, DegreePlan, RequirementNode).
  ingestion/     Scrapers and dataset loaders. Run offline; output cached in datasets/.
```

**Layer rules:** `domain/` imports nothing from the rest of the package. `planner/` and `optimisation/` import nothing from `cli/` or `services/`. `ingestion/` is never imported at runtime.

## Dataset

| File | Records | Notes |
|---|---|---|
| `courses.json` | 2,766 | Codes, titles, credits, levels, offerings, prerequisites (flat-list format). |
| `majors.json` | 380 | Required courses and elective pools per major (scraped April 2026). |
| `qualifications.json` | 176 | NZQF level, duration, degree type. |
| `specialisations.json` | 380 | Maps each major to its parent qualification. |

1,963 of 2,766 courses have active offerings. 818 have prerequisites after filtering.

### Refreshing the dataset

Network access to `massey.ac.nz` required. Run from the repo root:

```bash
# Re-scrape all prerequisite data using the HTML-aware parser
# Test first with a small batch:
python -m coursemap.ingestion.refresh_prerequisites --limit 20 --log-level DEBUG
# Full run (~45 min at default 8 workers):
python -m coursemap.ingestion.refresh_prerequisites

# Re-scrape all major pages (required and elective courses)
python -m coursemap.ingestion.build_majors_dataset

# Backfill elective pool credit requirements from major pages
python -m coursemap.ingestion.backfill_elective_credits

# Check dataset health after any update
coursemap validate
```

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

192 tests: 122 unit tests and 70 integration tests against the real dataset.

**Unit tests** cover scheduler correctness, rebalancing and equalisation logic, prerequisite expression evaluation, requirement node satisfaction, elective selection, and dataset normalisation.

**Integration tests** cover: complete-data degrees (BHSc 360cr), partial-data degrees (BA English with free-elective gap), prerequisite ordering invariant across all 380 majors, prior-completed handling, part-time scheduling, oversized thesis papers (90cr), campus-only exclusions, name resolution and smart disambiguation, corrected gap arithmetic (pool targets vs all members), auto-fill completeness, double-major requirement satisfaction and shared-course deduplication, transfer-credits accounting, JSON export schema, and dataset schema validation.

## Known limitations

**Prerequisite structure.** Prerequisites are stored as flat lists from the original scraper, filtered to same-subject plausible pairs. AND/OR logic and cross-subject prerequisites (e.g. a CS course requiring a maths course) are recovered by re-running `refresh_prerequisites` against the live Massey website.

**`--auto-fill` with `--double-major`.** Fully supported as of v0.6.0. Pass both flags together to generate a complete, auto-filled double-major plan in a single command.

**Free electives.** BA, BSc, and BBus degrees specify 120–240cr of major content against a 360cr total. Without `--auto-fill`, the tool plans the major-specific portion, reports the credit gap, and suggests subject-area electives. With `--auto-fill`, it schedules those electives automatically.

**4 empty-tree majors.** "Expressive Arts and Media Studies – Bachelor of Communication" and three postgraduate/graduate certificates have no parseable course lists on their Massey pages. They fail cleanly with `ValueError: No courses left to schedule`.

**Distance coverage.** 1,963 courses have active offerings; of these, ~800 have D/DIS. Use `--campus M --mode INT` for Manawatu internal plans, which cover significantly more undergraduate courses.
