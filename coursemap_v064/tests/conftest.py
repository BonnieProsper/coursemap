"""
Pytest configuration — disables slowapi rate-limiting for the test suite.

slowapi's Limiter respects a simple boolean `enabled` attribute. Setting it
to False before any tests run means no request is ever counted against a
limit, eliminating 429 flakes when tests hit /api/plan more than 30 times.
"""
import pytest


@pytest.fixture(autouse=True, scope="session")
def disable_rate_limits():
    """Set limiter.enabled = False for the entire test session."""
    from coursemap.api.server import limiter
    limiter.enabled = False
    yield
    limiter.enabled = True
