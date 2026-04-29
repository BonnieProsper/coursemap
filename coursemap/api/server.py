from __future__ import annotations
import os
import re

import logging
from datetime import date as _date
from collections import deque
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from coursemap.domain.prerequisite import prereq_to_dict, prereq_to_human
from coursemap.ingestion.dataset_loader import load_courses, load_majors
from coursemap.ingestion.freshness import freshness_report
from coursemap.services.planner_service import PlannerService
from coursemap.validation.dataset_validator import validate_dataset
from coursemap.export.ical import plan_to_ical

logger = logging.getLogger(__name__)

_UI_HTML = (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm the dataset on startup so first request isn't slow."""
    _svc()
    yield

app = FastAPI(
    title="coursemap",
    description="Degree planner API for Massey University.",
    version="0.4.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ALLOWED_ORIGINS: comma-separated list of allowed origins for CORS.
# Defaults to "*" (open) for local dev. Set to your deployed domain in production.
# e.g.  ALLOWED_ORIGINS="https://coursemap.example.com"
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "*")
_allowed_origins: list[str] | str = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins != "*"
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ---------------------------------------------------------------------------
# Shared singletons - loaded once on first request
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _svc() -> PlannerService:
    """Load dataset and create PlannerService singleton (cached after first call)."""
    logger.info("Loading datasets…")
    courses = load_courses()
    majors  = load_majors()
    logger.info("Loaded %d courses, %d majors.", len(courses), len(majors))
    return PlannerService(courses, majors)


@lru_cache(maxsize=1)
def _courses() -> dict:
    return _svc().courses


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class PlanRequest(BaseModel):
    major: str = Field(..., description="Major name (partial match accepted).")
    double_major: str | None = Field(None, description="Second major for a combined plan.")
    start_year: int = Field(default_factory=lambda: _date.today().year, description="First calendar year of study.")
    start_semester: str = Field("S1", description="Starting semester: S1, S2, or SS.")
    max_credits: int = Field(60, ge=15, le=120, description="Credit cap per semester.")
    max_per_semester: int | None = Field(None, ge=1, le=10, description="Course count cap.")
    campus: str = Field("D", description="Campus code: D, M, A, W.")
    mode: str = Field("DIS", description="Delivery mode: DIS, INT, BLK.")
    completed: list[str] = Field(default_factory=list, description="Already-completed course codes.")
    transfer_credits: int = Field(0, ge=0, description="Prior-learning credit recognition.")
    prefer: list[str] = Field(default_factory=list, description="Elective codes to prioritise.")
    exclude: list[str] = Field(default_factory=list, description="Course codes to never schedule.")
    no_summer: bool = Field(True, description="Skip Summer School semesters.")
    auto_fill: bool = Field(False, description="Auto-fill free-elective gap with subject-area courses.")


class SemesterOut(BaseModel):
    year: int
    semester: str
    credits: int
    courses: list[dict]


class PlanOut(BaseModel):
    meta: dict
    semesters: list[SemesterOut]
    warnings: list[str] = Field(default_factory=list)
    filler_codes: list[str] = Field(default_factory=list)
    double_major_info: dict | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _course_to_dict(course) -> dict:
    # Distinct semesters this course runs in (any campus/mode)
    offered_sems = sorted(set(o.semester for o in course.offerings))
    return {
        "code":    course.code,
        "title":   course.title,
        "credits": course.credits,
        "level":   course.level,
        "subject": getattr(course, "subject", None),
        "description": getattr(course, "description", None),
        "offered_semesters": offered_sems,
        "offerings": [
            {"semester": o.semester, "campus": o.campus, "mode": o.mode}
            for o in course.offerings
        ],
        "prerequisites":             prereq_to_dict(course.prerequisites),
        "prerequisites_human":       prereq_to_human(course.prerequisites),
        "prereq_data_available":     course.prerequisites is not None,
        "prerequisite_expression":   prereq_to_dict(course.prerequisites),
        "restrictions":              list(getattr(course, "restrictions", None) or []),
    }


def _plan_to_out(
    plan,
    svc: PlannerService,
    req: PlanRequest,
    filler_codes: list[str] | None = None,
    double_info: dict | None = None,
    extra_warnings: list[str] | None = None,
) -> PlanOut:
    semesters_out = [
        SemesterOut(
            year=s.year,
            semester=s.semester,
            credits=s.total_credits(),
            courses=[_course_to_dict(c) for c in s.courses],
        )
        for s in plan.semesters
    ]

    major_name = req.major
    filler     = filler_codes or []

    # Resolve canonical name, gap, and degree total in one shot
    try:
        resolved     = svc.resolve_major(major_name)
        resolved_name = resolved[0]["name"]
    except (ValueError, IndexError):
        resolved_name = major_name

    gap          = svc.free_elective_gap(major_name, campus=req.campus, mode=req.mode)
    degree_total = svc.degree_total_credits(major_name)
    # If auto_fill was requested and filler codes were injected, the gap has
    # been addressed by the planner. Show the residual gap (total target minus
    # total credits actually scheduled) rather than the raw major-data gap.
    raw_gap = max(0, gap - plan.transfer_credits)
    if filler and req.auto_fill:
        credits_total = plan.total_credits() + plan.prior_credits() + plan.transfer_credits
        residual_gap = max(0, degree_total - credits_total)
    else:
        residual_gap = raw_gap

    meta: dict[str, Any] = {
        "major":            resolved_name,
        "campus":           req.campus,
        "mode":             req.mode,
        "start_year":       req.start_year,
        "start_semester":   req.start_semester,
        "credits_planned":  plan.total_credits(),
        "credits_prior":    plan.prior_credits(),
        "credits_transfer": plan.transfer_credits,
        "credits_total":    plan.total_credits() + plan.prior_credits() + plan.transfer_credits,
        "degree_target":    degree_total,
        "free_elective_gap": residual_gap,
        "raw_elective_gap":  raw_gap,
        "auto_filled_codes": filler if req.auto_fill else [],
    }

    # Compute prerequisite data coverage across all scheduled courses
    all_scheduled = [c for s in plan.semesters for c in s.courses]
    _total_courses   = len(all_scheduled)
    _with_data       = sum(1 for c in all_scheduled if c.prerequisites is not None)
    _missing_data    = [c.code for c in all_scheduled if c.prerequisites is None and c.level >= 200]
    meta["prereq_coverage"] = {
        "total_courses":       _total_courses,
        "courses_with_data":   _with_data,
        "coverage_pct":        round(100 * _with_data / _total_courses) if _total_courses else 100,
        "missing_data_codes":  _missing_data[:20],  # cap at 20 for response size
    }

    warnings: list[str] = list(extra_warnings or [])
    if req.exclude:
        excl_req = svc.student_excluded_required_courses(
            major_name, frozenset(req.exclude), campus=req.campus, mode=req.mode
        )
        if excl_req:
            warnings.append(
                f"Excluded course(s) are required by this degree: {', '.join(excl_req)}. "
                "Major requirements will NOT be satisfied."
            )

    dmi_out: dict | None = None
    if double_info:
        dmi_out = {
            "first_label":   double_info["first_label"],
            "second_label":  double_info["second_label"],
            "shared_codes":  sorted(double_info["shared_codes"]),
            "saved_credits": double_info["saved_credits"],
            "first_gap":     double_info["first_gap"],
            "second_gap":    double_info["second_gap"],
        }
        meta["double_major"] = dmi_out

    return PlanOut(
        meta=meta,
        semesters=semesters_out,
        warnings=warnings,
        filler_codes=filler,
        double_major_info=dmi_out,
    )


def _execute_plan(req: PlanRequest, svc: PlannerService):
    """
    Single authoritative plan generation dispatch - used by both /api/plan
    and /api/plan/ical so flags only need updating in one place.
    Returns (plan, filler_codes, double_info).
    """
    prior     = frozenset(req.completed)
    preferred = frozenset(req.prefer)
    excluded  = frozenset(req.exclude)
    common    = dict(
        max_credits_per_semester  = req.max_credits,
        max_courses_per_semester  = req.max_per_semester,
        campus                    = req.campus,
        mode                      = req.mode,
        start_year                = req.start_year,
        start_semester            = req.start_semester,
        prior_completed           = prior,
        preferred_electives       = preferred,
        excluded_courses          = excluded,
        no_summer                 = req.no_summer,
        transfer_credits          = req.transfer_credits,
    )

    if req.double_major and req.auto_fill:
        plan, double_info, filler = svc.generate_filled_double_major_plan(
            major_name=req.major, second_major_name=req.double_major, **common
        )
        return plan, list(filler), double_info

    if req.double_major:
        plan, double_info = svc.generate_double_major_plan(
            major_name=req.major, second_major_name=req.double_major, **common
        )
        return plan, [], double_info

    if req.auto_fill:
        plan, filler = svc.generate_filled_plan(major_name=req.major, **common)
        return plan, list(filler), None

    plan = svc.generate_best_plan(major_name=req.major, **common)
    return plan, [], None


# ---------------------------------------------------------------------------
# UI route
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_ui():
    """Serve the web planner UI."""
    return HTMLResponse(content=_UI_HTML)


# ---------------------------------------------------------------------------
# API routes (all under /api prefix)
# ---------------------------------------------------------------------------

@app.get("/api", summary="API info and dataset status")
def api_root():
    fr = freshness_report()
    return {
        "name":    "coursemap",
        "version": "0.6.4",
        "description": "Massey University degree planner",
        "docs":    "/docs",
        "dataset": fr,
    }


@app.get("/api/freshness", summary="Dataset age and staleness report")
def get_freshness():
    return freshness_report()


@app.get("/api/data-quality", summary="Dataset quality report")
def data_quality_report():
    """
    Return a structured report on prerequisite data coverage and freshness.
    Useful for surfacing data gaps in the UI and for CI health checks.
    """
    import json as _json
    from collections import Counter as _Counter
    from coursemap.ingestion.dataset_loader import DATASET_PATH

    # Raw format distribution
    with open(DATASET_PATH, encoding="utf-8") as f:
        raw_courses = _json.load(f)

    fmt: dict[str, int] = _Counter()
    for c in raw_courses:
        pval = c.get("prerequisites")
        if pval is None:
            fmt["null"] += 1
        elif isinstance(pval, list):
            fmt["flat_list"] += 1
        elif isinstance(pval, dict):
            fmt["and_or_tree"] += 1
        elif isinstance(pval, str):
            fmt["single_code"] += 1

    total   = len(raw_courses)
    new_fmt = fmt.get("and_or_tree", 0) + fmt.get("single_code", 0)
    old_fmt = fmt.get("flat_list", 0)

    courses = _svc().courses
    with_prereqs = sum(1 for c in courses.values() if c.prerequisites is not None)

    freshness = freshness_report()

    return {
        "total_courses":          total,
        "prerequisite_formats":   dict(fmt),
        "structured_pct":         round(100 * new_fmt / total) if total else 0,
        "courses_with_prereqs_after_filter": with_prereqs,
        "courses_null_after_filter":         total - with_prereqs,
        "needs_rescrape":         old_fmt + fmt.get("null", 0),
        "freshness":              freshness,
        "recommendation":         (
            "Run `python -m coursemap.ingestion.refresh_prerequisites` to upgrade "
            f"{old_fmt + fmt.get('null', 0)} courses to structured AND/OR prerequisites."
        ) if (old_fmt + fmt.get("null", 0)) > 0 else "All courses use structured prerequisite format.",
    }


@app.get("/api/majors", summary="List or search majors")
@limiter.limit("200/minute")
def list_majors(
    request: Request,
    search: str | None = Query(None, description="Partial name search query."),
    limit:  int        = Query(50,   ge=1, le=500, description="Max results."),
):
    svc = _svc()
    majors = svc.majors

    if search:
        words = search.strip().lower().split()
        def word_match(name: str) -> bool:
            tokens = name.lower().replace("–", " ").split()
            return all(any(w in tok for tok in tokens) for w in words)
        majors = [m for m in majors if word_match(m["name"])]

    majors = sorted(majors, key=lambda m: m["name"])[:limit]

    def _parse_qual(name: str) -> str:
        """Extract qualification type from major name: 'CS – Bachelor of Science' → 'Bachelor of Science'."""
        parts = re.split(r"\s+[\u2013\u2014-]\s+", name, maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    return {
        "count":  len(majors),
        "majors": [
            {
                "name":               m["name"],
                "url":                m.get("url", ""),
                "qualification_type": _parse_qual(m["name"]),
            }
            for m in majors
        ],
    }


@app.get("/api/majors/resolve", summary="Resolve a major name to a canonical match")
def resolve_major(name: str = Query(..., description="Major name (partial match accepted).")):
    svc = _svc()
    try:
        resolved = svc.resolve_major(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "count":  len(resolved),
        "majors": [{"name": m["name"], "url": m.get("url", "")} for m in resolved],
    }


@app.get("/api/courses", summary="Browse course catalogue")
def list_courses(
    search: str | None = Query(None, description="Title keyword search."),
    level:  int | None = Query(None, description="Filter by level (100, 200, …)."),
    campus: str | None = Query(None, description="Filter by campus code."),
    mode:   str | None = Query(None, description="Filter by delivery mode."),
    limit:  int        = Query(50, ge=1, le=3000, description="Max results."),
):
    courses = list(_courses().values())

    if search:
        words = search.strip().lower().split()
        courses = [c for c in courses if all(w in c.title.lower() for w in words)]
    if level is not None:
        courses = [c for c in courses if c.level == level]
    if campus:
        courses = [c for c in courses if any(o.campus == campus for o in c.offerings)]
    if mode:
        courses = [c for c in courses if any(o.mode == mode for o in c.offerings)]

    courses = [c for c in courses if c.offerings]
    courses.sort(key=lambda c: (c.level, c.code))

    return {
        "count":   len(courses),
        "courses": [_course_to_dict(c) for c in courses[:limit]],
    }


@app.get("/api/courses/{code}", summary="Single course detail")
def get_course(code: str):
    courses = _courses()
    code = code.upper()
    if code not in courses:
        raise HTTPException(status_code=404, detail=f"Course '{code}' not found.")
    return _course_to_dict(courses[code])


@app.get("/api/courses/{code}/prereq-chain", summary="Full prerequisite chain for a course")
def get_prereq_chain(code: str):
    """
    Return the full transitive prerequisite chain for a course as a DAG suitable
    for rendering. Each node in `nodes` has {code, title, credits, level}.
    Each edge in `edges` is {from, to}. `depth` gives the longest chain length
    (minimum semesters before this course can be taken).
    """
    courses = _courses()
    code = code.upper()
    if code not in courses:
        raise HTTPException(status_code=404, detail=f"Course '{code}' not found.")

    from coursemap.domain.prerequisite import CoursePrerequisite, AndExpression, OrExpression

    def direct_prereqs(c_code: str) -> set[str]:
        course = courses.get(c_code)
        if not course or not course.prerequisites:
            return set()
        result: set[str] = set()
        stack = [course.prerequisites]
        while stack:
            node = stack.pop()
            if isinstance(node, CoursePrerequisite):
                if node.code in courses:
                    result.add(node.code)
            elif isinstance(node, (AndExpression, OrExpression)):
                stack.extend(node.children)
        return result

    # BFS using deque (O(1) popleft vs O(n) pop(0))
    visited: set[str] = set()
    edges: list[dict] = []
    queue: deque[str] = deque([code])
    while queue:
        cur = queue.popleft()
        if cur in visited:
            continue
        visited.add(cur)
        for dep in direct_prereqs(cur):
            edges.append({"from": dep, "to": cur})
            if dep not in visited:
                queue.append(dep)

    # Compute depth (longest path from any root to each node) via relaxation
    depths: dict[str, int] = {n: 0 for n in visited}
    changed = True
    while changed:
        changed = False
        for e in edges:
            new_d = depths[e["from"]] + 1
            if new_d > depths[e["to"]]:
                depths[e["to"]] = new_d
                changed = True

    nodes = [
        {
            "code":    c,
            "title":   courses[c].title if c in courses else c,
            "credits": courses[c].credits if c in courses else 0,
            "level":   courses[c].level if c in courses else 0,
            "depth":   depths.get(c, 0),
        }
        for c in visited
    ]
    nodes.sort(key=lambda n: n["depth"])

    return {
        "code":        code,
        "nodes":       nodes,
        "edges":       edges,
        "chain_depth": depths.get(code, 0),
    }


@app.get("/api/courses/{code}/explain", summary="Explain why a course appears where it does in a plan")
def explain_course(
    code: str,
    major: str = Query(..., description="Major name."),
    campus: str = Query("D"),
    mode:   str = Query("DIS"),
):
    """
    Return a human-readable explanation of scheduling constraints for a course:
    - Which prerequisites it needs and when they become available
    - What offering semesters are available for this campus/mode
    - How deep its prerequisite chain is
    """
    courses = _courses()
    code = code.upper()
    if code not in courses:
        raise HTTPException(status_code=404, detail=f"Course '{code}' not found.")

    course = courses[code]

    # Offerings at requested campus/mode
    matching_offerings = [
        {"semester": o.semester, "campus": o.campus, "mode": o.mode}
        for o in course.offerings
        if o.campus == campus and o.mode == mode
    ]
    all_offerings = [
        {"semester": o.semester, "campus": o.campus, "mode": o.mode}
        for o in course.offerings
    ]

    # Get prereq chain depth
    chain_data = get_prereq_chain(code)
    chain_depth = chain_data["chain_depth"]

    # Build constraint summary
    constraints: list[str] = []

    if not course.offerings:
        constraints.append("This course has no recorded offerings - it may be discontinued or offered by arrangement only.")
    elif not matching_offerings:
        avail = sorted({f"{o['campus']}/{o['mode']}" for o in all_offerings})
        constraints.append(
            f"Not offered at {campus}/{mode}. Available at: {', '.join(avail)}."
        )
    else:
        sems = sorted({o["semester"] for o in matching_offerings})
        constraints.append(f"Offered at {campus}/{mode} in: {', '.join(sems)}.")

    if chain_depth == 0:
        if matching_offerings:
            sems_avail = sorted({o["semester"] for o in matching_offerings})
            first_sem = sems_avail[0]  # S1 < S2 < SS alphabetically by convention
            constraints.append(f"No prerequisites - can be taken in {first_sem} of year 1.")
        else:
            constraints.append("No prerequisites - can be taken in semester 1 (subject to offering availability).")
    else:
        # Compute a more accurate earliest-semester estimate that accounts for
        # offering constraints. Each semester slot is S1→S2→SS repeating.
        # The chain_depth tells us the minimum number of prior semesters needed.
        # If the course is only offered in one semester type, it may need to wait
        # an extra slot after prerequisites are met.
        sem_cycle = ["S1", "S2", "SS"]
        # Simulate: after chain_depth slots of prerequisites, what slot can this course land in?
        prereq_finish_slot = chain_depth - 1   # 0-indexed slot where last prereq finishes
        earliest_take_slot = chain_depth        # earliest slot to take this course (0-indexed)
        if matching_offerings:
            offered_sems = {o["semester"] for o in matching_offerings}
            # Walk forward from earliest_take_slot until we find a slot with a matching semester
            for offset in range(6):  # max 6 extra slots to find a matching semester
                candidate_sem = sem_cycle[(earliest_take_slot + offset) % 3]
                if candidate_sem in offered_sems:
                    earliest_take_slot += offset
                    break
        # Convert 0-indexed slot to human semester number (slot 0 = "semester 1")
        earliest_sem_number = earliest_take_slot + 1
        constraints.append(
            f"Prerequisite chain is {chain_depth} semester{'s' if chain_depth != 1 else ''} deep - "
            f"earliest possible semester: {earliest_sem_number}."
        )

    if course.prerequisites:
        prereq_str = prereq_to_human(course.prerequisites)
        constraints.append(f"Requires: {prereq_str}.")

    return {
        "code":               code,
        "title":              course.title,
        "credits":            course.credits,
        "level":              course.level,
        "offerings_matching": matching_offerings,
        "offerings_all":      all_offerings,
        "prerequisites_human": prereq_to_human(course.prerequisites),
        "chain_depth":        chain_depth,
        "constraints":        constraints,
    }


@app.post("/api/plan", response_model=PlanOut, summary="Generate a degree plan")
@limiter.limit("30/minute")
def generate_plan(request: Request, req: PlanRequest):
    svc = _svc()

    # Warn about unknown codes in user-supplied lists (before planning).
    catalogue = _courses()
    unknown_warnings: list[str] = []
    for label, codes in [("completed", req.completed), ("prefer", req.prefer), ("exclude", req.exclude)]:
        unknown = [c for c in codes if c not in catalogue]
        if unknown:
            unknown_warnings.append(
                f"Unknown course code(s) in '{label}': {', '.join(unknown)}. These will be ignored."
            )

    try:
        plan, filler, double_info = _execute_plan(req, svc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _plan_to_out(plan, svc, req, filler_codes=filler, double_info=double_info, extra_warnings=unknown_warnings)


@app.post("/api/plan/ical", summary="Generate a degree plan and return an .ics calendar file")
@limiter.limit("10/minute")
def generate_plan_ical(request: Request, req: PlanRequest):
    svc = _svc()

    try:
        plan, _, double_info = _execute_plan(req, svc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Resolve label for calendar name
    if double_info:
        major_label = f"{double_info['first_label']} + {double_info['second_label']}"
    else:
        try:
            major_label = svc.resolve_major(req.major)[0]["name"]
        except (ValueError, IndexError):
            major_label = req.major

    ics_content = plan_to_ical(plan, major_label, campus=req.campus, mode=req.mode)
    import re as _re
    safe_name = _re.sub(r'[^\w\s-]', '', req.major.replace('–', '-').replace('-', '-'))
    filename = f"degree_plan_{safe_name.replace(' ', '_')[:40]}.ics"
    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/validate", summary="Dataset integrity report")
def validate():
    svc = _svc()
    result = validate_dataset(svc.courses, svc.majors, raise_on_error=False)
    return {
        "errors":        result.errors,
        "warnings":      result.warnings[:50],
        "error_count":   len(result.errors),
        "warning_count": len(result.warnings),
        "passed":        len(result.errors) == 0,
    }


@app.post("/api/plan/validate", summary="Validate a plan against its degree requirements")
def validate_plan(req: PlanRequest):
    """
    Generate a plan and validate it against the full degree requirement tree.
    Returns a structured checklist of passed/failed requirements.
    """
    svc = _svc()

    try:
        plan, _, _ = _execute_plan(req, svc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    from coursemap.validation.engine import DegreeValidator
    from coursemap.domain.requirement_nodes import (
        AllOfRequirement, AnyOfRequirement, ChooseCreditsRequirement,
        ChooseNRequirement, CourseRequirement, MajorRequirement,
        MaxLevelCreditsRequirement, MinLevelCreditsFromRequirement,
        MinLevelCreditsRequirement, TotalCreditsRequirement,
    )

    try:
        tree = svc.degree_tree_for_major(req.major)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail=f"Could not build requirement tree for '{req.major}'.")

    validator = DegreeValidator(tree)
    result = validator.validate(plan)

    # Also build a human-readable checklist from the tree
    courses = _courses()
    plan_codes = set(plan.all_course_codes)

    def node_to_check(node, depth=0) -> dict:
        """Recursively convert a requirement node to a UI-renderable checklist item."""
        if isinstance(node, CourseRequirement):
            c = courses.get(node.course_code)
            passed = node.course_code in plan_codes
            return {
                "type": "course",
                "code": node.course_code,
                "title": c.title if c else node.course_code,
                "credits": c.credits if c else 0,
                "passed": passed,
                "label": f"{node.course_code} - {c.title if c else '?'}",
            }

        if isinstance(node, TotalCreditsRequirement):
            total = plan.total_credits() + plan.prior_credits()
            return {
                "type": "total_credits",
                "required": node.required_credits,
                "actual": total,
                "passed": total >= node.required_credits,
                "label": f"Total credits: {total} / {node.required_credits}cr required",
            }

        if isinstance(node, MinLevelCreditsRequirement):
            total = sum(c.credits for s in plan.semesters for c in s.courses if c.level == node.level)
            return {
                "type": "min_level",
                "level": node.level,
                "required": node.min_credits,
                "actual": total,
                "passed": total >= node.min_credits,
                "label": f"Level {node.level} credits: {total} / {node.min_credits}cr minimum",
            }

        if isinstance(node, MaxLevelCreditsRequirement):
            total = sum(c.credits for s in plan.semesters for c in s.courses if c.level == node.level)
            return {
                "type": "max_level",
                "level": node.level,
                "limit": node.max_credits,
                "actual": total,
                "passed": total <= node.max_credits,
                "label": f"Level {node.level} credits: {total} / max {node.max_credits}cr",
            }

        if isinstance(node, ChooseCreditsRequirement):
            allowed = set(node.course_codes)
            total = sum(c.credits for s in plan.semesters for c in s.courses if c.code in allowed)
            total += sum(c.credits for c in plan.prior_completed if c.code in allowed)
            return {
                "type": "choose_credits",
                "required": node.credits,
                "actual": total,
                "pool_size": len(node.course_codes),
                "passed": total >= node.credits or node.credits <= 0,
                "label": f"Elective pool: {total} / {node.credits}cr from {len(node.course_codes)} courses",
                "pool_codes": list(node.course_codes)[:20],
            }

        if isinstance(node, ChooseNRequirement):
            chosen = sum(1 for code in node.course_codes if code in plan_codes)
            return {
                "type": "choose_n",
                "required": node.n,
                "actual": chosen,
                "passed": chosen >= node.n,
                "label": f"Choose courses: {chosen} / {node.n} required",
                "pool_codes": list(node.course_codes)[:20],
            }

        if isinstance(node, (AllOfRequirement, MajorRequirement)):
            children_nodes = node.children if hasattr(node, "children") else [node.requirement]
            checks = [node_to_check(c, depth + 1) for c in children_nodes]
            passed = all(c["passed"] for c in checks)
            return {
                "type": "all_of",
                "passed": passed,
                "label": "All of the following",
                "children": checks,
            }

        if isinstance(node, AnyOfRequirement):
            checks = [node_to_check(c, depth + 1) for c in node.children]
            passed = any(c["passed"] for c in checks)
            return {
                "type": "any_of",
                "passed": passed,
                "label": "Any of the following",
                "children": checks,
            }

        return {"type": "unknown", "passed": True, "label": str(type(node).__name__)}

    checklist = node_to_check(tree)

    return {
        "passed": result.passed,
        "errors": result.errors,
        "checklist": checklist,
        "summary": {
            "credits_planned": plan.total_credits(),
            "credits_prior": plan.prior_credits(),
            "credits_total": plan.total_credits() + plan.prior_credits(),
        },
    }
