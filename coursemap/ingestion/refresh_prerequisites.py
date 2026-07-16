"""
Refresh prerequisite, restriction, and corequisite data in datasets/courses.json
using the HTML-aware scraper.

Reads the existing courses.json, fetches each course's Massey page once to
extract structured prerequisites (AND/OR logic) plus flat restriction and
corequisite code lists, then writes the updated file back.

No Swiftype API key required -- only direct HTTP fetches to Massey's site.

Run from the repo root:

    python -m coursemap.ingestion.refresh_prerequisites

Options:
    --concurrency N   Parallel fetch workers (default: 20).
    --timeout N       Per-request timeout in seconds (default: 10).
    --limit N         Only process the first N courses (useful for testing).
    --dry-run         Parse and report without writing courses.json.
    --log-level       DEBUG | INFO | WARNING | ERROR (default: INFO).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from coursemap.ingestion.prerequisite_scraper import (
    scrape_course_relations,
    _extract_prerequisite_codes,
)

logger = logging.getLogger(__name__)

_DATASETS_DIR = Path(__file__).resolve().parents[2] / "datasets"
_COURSES_PATH = _DATASETS_DIR / "courses.json"


# Every genuinely healthy Massey course page fetched during this
# investigation (two separate real dry-runs, ~30 courses total) was
# between 9872 and 11097 bytes. A response drastically smaller than that
# under a nominal HTTP 200 is far more likely to be a truncated page
# from a degraded connection than a real, unusually short course page -
# this is what actually caught the corruption a plain status-code check
# didn't: one confirmed case (course 234338) came back HTTP 200, no
# exception, with a genuine but truncated OR-group and a second required
# course silently missing entirely.
_SUSPICIOUSLY_SHORT_RESPONSE_BYTES = 5000

# Backoff schedule, indexed by attempt number (1-based). The original
# version used `random.uniform(0.1, 0.5) * attempt`, topping out under
# 1.5s by the third attempt - long enough to dodge a brief transient
# blip, but not remotely long enough to land outside a sustained,
# multi-minute throttling window if that's the real cause (still
# unconfirmed - see DATA_QUALITY.md). Unlike _SUSPICIOUSLY_SHORT_RESPONSE_BYTES
# above, these specific numbers are a reasoned judgment call, not
# something backed by observed data from this run - direction (retry
# later attempts much more slowly) is what matters, the exact seconds
# are a starting point to revise once a real run's retry behavior is
# actually observed.
_BACKOFF_RANGES_BY_ATTEMPT = {
    1: (0.1, 0.5),
    2: (3.0, 6.0),
    3: (10.0, 15.0),
}
_MAX_FETCH_ATTEMPTS = 3

# A 404 or 410 means the resource genuinely doesn't exist right now (the
# course was removed, renamed, or the URL is stale) - retrying with
# backoff can't fix that, unlike a truncated response or a transient
# error, so these short-circuit immediately rather than burning through
# the full retry schedule (up to ~19s wasted per course otherwise, every
# single run, forever, for a condition that will never change until the
# underlying data is corrected some other way).
_PERMANENT_FAILURE_STATUS_CODES = {404, 410}

# If the untouched-course rate crosses this share of courses processed
# so far, something systemic is likely happening.
# Gated by _UNTOUCHED_WARNING_MIN_SAMPLE so a noisy early sample
# (e.g. 2 of the first 10 completions) doesn't false-trigger before the
# rate is actually meaningful.
#
# Deliberately only counts transient (retry-exhausted) failures, not
# permanent ones (see _PERMANENT_FAILURE_STATUS_CODES) - a catalogue
# with some baseline of discontinued/moved courses would otherwise create
# a constant noise floor in this rate that has nothing to do with the
# systemic-throttling problem this check exists to catch, potentially
# either false-triggering on a normal run or making the check useless if
# the baseline is already close to the threshold on its own.
_UNTOUCHED_WARNING_THRESHOLD = 0.10
_UNTOUCHED_WARNING_MIN_SAMPLE = 50


def _is_suspicious_regression(
    existing: dict[str, Any], fresh: dict[str, Any],
) -> tuple[bool, str]:
    """
    Compare a freshly-scraped result against a course's currently-stored
    value. Returns (is_suspicious, reason).

    A field is flagged only when the existing stored value is non-empty
    AND the fresh value's code set is a *strict subset* of it (fewer
    codes, nothing new). This is deliberately narrow:

    - No existing data -> never suspicious. A first-time scrape finding
      something is progress, not a regression, regardless of how little
      or much it finds.
    - Fresh set equal to or a superset of existing -> never suspicious.
      Massey genuinely adding a prerequisite option over time must not
      trip this.
    - Fresh set partially overlapping but with different elements
      neither a subset nor superset of existing -> NOT flagged. No real
      incident has shown this pattern; a real one might in the future,
      but flagging it now would be guessing at a failure mode with zero
      evidence, and risks false-triggering on legitimate content changes.

    Checks all three fields (prerequisites via _extract_prerequisite_codes,
    restrictions/corequisites directly as flat lists) independently, since
    each can regress on its own.

    Root cause: a real production incident (see DATA_QUALITY.md) where
    sustained scraping - reproduced twice, at very different speeds -
    returned an apparently healthy HTTP 200 response containing fewer
    prerequisite codes than were already known-correct, for several
    different courses, byte-for-byte identically each time. Neither the
    response's HTTP status nor its overall byte length looked wrong in
    any of these cases, which is why neither existing check caught it.
    """
    old_prereq_codes = _extract_prerequisite_codes(existing.get("prerequisites"))
    new_prereq_codes = _extract_prerequisite_codes(fresh.get("prerequisites"))
    if old_prereq_codes and new_prereq_codes < old_prereq_codes:
        missing = old_prereq_codes - new_prereq_codes
        return True, (
            f"prerequisites regressed: fresh fetch is missing "
            f"{sorted(missing)} that the stored value already had"
        )

    for field in ("restrictions", "corequisites"):
        old_set = set(existing.get(field) or [])
        new_set = set(fresh.get(field) or [])
        if old_set and new_set < old_set:
            missing = old_set - new_set
            return True, (
                f"{field} regressed: fresh fetch is missing "
                f"{sorted(missing)} that the stored value already had"
            )

    return False, ""


def _fetch_relations(
    code: str, url: str, timeout: int, existing: dict[str, Any],
) -> tuple[str, dict[str, Any], bool, bool]:
    """
    Fetch one course page and return (code, relations_dict, reliable,
    permanent_failure), where relations_dict has "prerequisites" /
    "restrictions" / "corequisites" keys (see `scrape_course_relations`).

    reliable is False if every attempt looked suspicious, by either of
    two independent checks: the response was suspiciously short (see
    _SUSPICIOUSLY_SHORT_RESPONSE_BYTES above - catches a truncated or
    blocked response), or the freshly-scraped codes are a strict subset
    of what's already stored for this course (see
    _is_suspicious_regression above - catches an apparently-healthy
    response that's nonetheless missing data we already know is
    correct, the failure mode that actually corrupted several courses
    in a real production run even though every response
    was HTTP 200 at a normal size). Either way, the caller must leave
    that course's existing data untouched rather than overwrite it with
    an unconfirmed result, however plausible-looking. Silently writing
    the last attempt's data regardless of confidence is exactly how that
    incident happened: retries alone aren't enough if the caller still
    trusts a result that never actually got confirmed.

    permanent_failure is True only for a 404/410 (see
    _PERMANENT_FAILURE_STATUS_CODES) - the caller should track this
    separately from an ordinary "reliable=False", since it means "this
    course's URL doesn't work right now" rather than "we couldn't get a
    confident answer this run, try again later". Short-circuits
    immediately on the first permanent-failure response rather than
    exhausting the retry schedule for a condition retrying can't fix.

    Backoff grows sharply across attempts (see _BACKOFF_RANGES_BY_ATTEMPT
    above) rather than staying near-instant, on the theory that a
    same-second retry is unlikely to escape whatever caused the first
    attempt to look suspicious if it's a sustained condition rather than
    a one-off blip.
    """
    last_result: dict[str, Any] = {"prerequisites": None, "restrictions": [], "corequisites": []}
    for attempt in range(1, _MAX_FETCH_ATTEMPTS + 1):
        low, high = _BACKOFF_RANGES_BY_ATTEMPT[attempt]
        time.sleep(random.uniform(low, high))
        result = scrape_course_relations(url, timeout=timeout, include_diagnostics=True)
        status = result.pop("_status_code")
        content_length = result.pop("_content_length")
        last_result = result

        if status in _PERMANENT_FAILURE_STATUS_CODES:
            logger.debug("Permanent failure (HTTP %s) for %s, not retrying.", status, code)
            return code, last_result, False, True

        if status == 200 and content_length >= _SUSPICIOUSLY_SHORT_RESPONSE_BYTES:
            is_regression, reason = _is_suspicious_regression(existing, result)
            if not is_regression:
                return code, result, True, False
            reason_str = reason
        else:
            reason_str = (
                f"content_length={content_length} (expected >= "
                f"{_SUSPICIOUSLY_SHORT_RESPONSE_BYTES})"
            )

        if attempt < _MAX_FETCH_ATTEMPTS:
            logger.warning(
                "Suspicious fetch for %s (attempt %d/%d): status=%s, %s. Retrying.",
                code, attempt, _MAX_FETCH_ATTEMPTS, status, reason_str,
            )
        else:
            logger.warning(
                "Giving up on %s after %d attempts (last: status=%s, %s). "
                "This course's existing data will be left untouched rather "
                "than overwritten with an unconfirmed result.",
                code, _MAX_FETCH_ATTEMPTS, status, reason_str,
            )

    return code, last_result, False, False


def refresh_prerequisites(
    courses_path: Path = _COURSES_PATH,
    concurrency: int = 20,
    timeout: int = 10,
    limit: int | None = None,
    dry_run: bool = False,
    only_missing: bool = False,
) -> None:
    """
    Re-scrape prerequisites, restrictions, and corequisites for all courses
    and update courses.json. One page fetch per course covers all three.

    Args:
        courses_path:  Path to courses.json.
        concurrency:   Number of parallel HTTP workers.
        timeout:       Per-request timeout in seconds.
        limit:         Cap on courses to process (None = all).
        dry_run:       If True, report changes without writing.
        only_missing:  If True, skip courses already using structured
                       (dict or str) prerequisite format. Only re-scrape
                       flat-list and null prerequisite entries. This flag
                       is keyed on prerequisites only, since an empty
                       restriction/corequisite list is indistinguishable
                       from "genuinely has none" once this fix has run once;
                       there's no cheap signal to detect "still unscraped"
                       for those two fields the way there is for prerequisites.
    """
    with open(courses_path, encoding="utf-8") as f:
        courses = json.load(f)

    # Build a map of code -> index for fast update
    index: dict[str, int] = {
        c["course_code"]: i
        for i, c in enumerate(courses)
        if c.get("course_code") and c.get("url")
    }

    to_process = [
        (
            c["course_code"],
            c["url"],
            {
                "prerequisites": c.get("prerequisites"),
                "restrictions": c.get("restrictions") or [],
                "corequisites": c.get("corequisites") or [],
            },
        )
        for c in courses
        if c.get("course_code") and c.get("url")
        and (not only_missing or not isinstance(c.get("prerequisites"), (dict, str)))
    ]

    if limit:
        to_process = to_process[:limit]

    total = len(to_process)
    logger.info(
        "Scraping prerequisites/restrictions/corequisites for %d courses (concurrency=%d)...",
        total, concurrency,
    )

    updated = 0
    prereq_found = 0
    restriction_found = 0
    coreq_found = 0
    left_untouched = 0
    permanently_missing = 0
    done = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_fetch_relations, code, url, timeout, existing): code
            for code, url, existing in to_process
        }
        for future in as_completed(futures):
            code = futures[future]
            done += 1

            try:
                result_code, relations, reliable, permanent_failure = future.result()
            except Exception as exc:
                logger.warning("Unexpected error for %s: %s", code, exc)
                # Same category as a suspicious-fetch failure: no confirmed
                # data, nothing written, safe to retry later - and just as
                # relevant to the systemic-problem check below, so it must
                # not bypass it via an early return.
                left_untouched += 1
            else:
                if permanent_failure:
                    permanently_missing += 1
                elif not reliable:
                    left_untouched += 1
                elif result_code in index:
                    idx = index[result_code]
                    courses[idx]["prerequisites"] = relations["prerequisites"]
                    courses[idx]["restrictions"] = relations["restrictions"]
                    courses[idx]["corequisites"] = relations["corequisites"]
                    if relations["prerequisites"] is not None:
                        prereq_found += 1
                    if relations["restrictions"]:
                        restriction_found += 1
                    if relations["corequisites"]:
                        coreq_found += 1
                    if relations["prerequisites"] is not None or relations["restrictions"] or relations["corequisites"]:
                        updated += 1

            if done % 100 == 0:
                logger.info("Progress: %d/%d", done, total)
                # Rate is left_untouched (transient failures only) over
                # done (everything processed so far, including permanent
                # failures) - a deliberately simple, slightly conservative
                # denominator rather than also excluding permanently_missing
                # from it, so the rate stays easy to explain: "of
                # everything touched so far, what share ended up
                # transiently unresolved". Permanent failures are already
                # reported separately below.
                if done >= _UNTOUCHED_WARNING_MIN_SAMPLE:
                    untouched_rate = left_untouched / done
                    if untouched_rate > _UNTOUCHED_WARNING_THRESHOLD:
                        logger.warning(
                            "*** %d of %d courses processed so far (%.0f%%) were left "
                            "untouched after repeated suspicious fetches - this may mean "
                            "something systemic is happening (rate limiting, a site change) "
                            "rather than isolated blips. The run will continue, but consider "
                            "stopping (Ctrl+C) and investigating rather than waiting for it "
                            "to finish. ***",
                            left_untouched, done, untouched_rate * 100,
                        )

    logger.info(
        "Scraped %d courses; %d have at least one of prereq/restriction/corequisite "
        "(prereq: %d, restriction: %d, corequisite: %d). %d course(s) left "
        "untouched after repeated suspicious fetches (see warnings above) - "
        "re-run later to pick those up, they were not overwritten. %d course(s) "
        "returned a permanent failure (404/410) and were left untouched without "
        "retrying - if this number looks unexpectedly large, it may be worth "
        "checking whether specialisations.json or courses.json URLs are stale, "
        "rather than assuming it's just normal catalogue turnover.",
        total, updated, prereq_found, restriction_found, coreq_found, left_untouched,
        permanently_missing,
    )

    if total > 0 and left_untouched / total > _UNTOUCHED_WARNING_THRESHOLD:
        logger.warning(
            "*** %d/%d courses (%.0f%%) were left untouched this run - well above "
            "the %d%% threshold that's normally expected from isolated blips. "
            "Before trusting the rest of this run's data, consider re-running "
            "(courses left untouched are safe to retry; nothing was overwritten "
            "for them) and checking whether the rate drops. ***",
            left_untouched, total, (left_untouched / total) * 100,
            int(_UNTOUCHED_WARNING_THRESHOLD * 100),
        )

    # Safety: if we got 0 data from 100+ courses, something is broken.
    # Massey may have changed their HTML, or the requests are being blocked.
    # Refuse to overwrite the dataset to avoid wiping working data.
    if updated == 0 and total > 100:
        logger.error(
            "ABORTED: scraped %d courses but found 0 prerequisites, restrictions, "
            "or corequisites across all of them. "
            "This almost certainly means Massey's page structure has changed "
            "or requests are being blocked (check for 403/captcha responses). "
            "courses.json was NOT modified. "
            "Run with --limit 5 --dry-run to inspect raw responses.",
            total,
        )
        return

    # Safety: prerequisites collapsing to 0 specifically, even when
    # restrictions/corequisites are non-zero, is not caught by the check
    # above. Restrictions and corequisites are known-sparse under normal
    # conditions (~24% of the catalogue per DATA_QUALITY.md), so a low
    # count there alone doesn't mean something broke -- but essentially
    # every course path in this codebase treats "has prerequisites" as
    # the common case, so prerequisites hitting exactly 0 across 100+
    # real Massey courses means the HTML structure Strategy 1 depends on
    # (course-intro__col-header) most likely changed, even if restriction/
    # corequisite extraction happens to still work. Without this check,
    # that scenario silently overwrites every course's prerequisites with
    # None -- the single field this whole script exists to refresh.
    if prereq_found == 0 and total > 100:
        logger.error(
            "ABORTED: scraped %d courses and found restriction/corequisite data "
            "for some of them (restriction: %d, corequisite: %d), but found 0 "
            "prerequisites across all of them. The combined success check above "
            "did not catch this because it only requires ANY of the three "
            "fields to be non-empty. This specific pattern means prerequisite "
            "extraction (Strategy 1 in prerequisite_scraper.py, which depends "
            "on the exact 'course-intro__col-header' CSS class) most likely "
            "broke while the other extraction paths kept working. "
            "courses.json was NOT modified. "
            "Run with --limit 5 --dry-run --log-level DEBUG to inspect raw responses.",
            total, restriction_found, coreq_found,
        )
        return

    if dry_run:
        logger.info("Dry run, courses.json not modified.")
        return

    # Atomic write
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=courses_path.parent,
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        json.dump(courses, tmp, indent=2, ensure_ascii=False)

    os.replace(tmp_path, courses_path)
    logger.info("Wrote updated courses.json.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--concurrency", type=int, default=8, metavar="N",
        help="Parallel fetch workers (default: 8). Keep low to avoid CDN rate limits.",
    )
    parser.add_argument(
        "--timeout", type=int, default=10, metavar="N",
        help="Per-request timeout in seconds (default: 10).",
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Only process the first N courses (for testing).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Parse and report without writing courses.json.",
    )
    parser.add_argument(
        "--only-missing", action="store_true", default=False,
        help=(
            "Skip courses that already have structured (AND/OR dict or single-code str) "
            "prerequisite data. Useful for incremental updates after a partial run."
        ),
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    refresh_prerequisites(
        concurrency=args.concurrency,
        timeout=args.timeout,
        limit=args.limit,
        dry_run=args.dry_run,
        only_missing=args.only_missing,
    )
