"""
Pytest configuration: disables slowapi rate-limiting for the test suite.

slowapi's Limiter respects a simple boolean `enabled` attribute. Setting it
to False before any tests run means no request is ever counted against a
limit, eliminating 429 flakes when tests hit /api/plan more than 30 times.
"""
import pytest


def full_ui_text(client) -> str:
    """
    Concatenate the served page with its external CSS/JS.

    ui.html's CSS and JS live in coursemap/api/static/app.css and app.js,
    served separately, not inlined into GET / - a test checking whether some
    markup or JS logic exists in "the UI" needs all three, not just the page.
    """
    return (
        client.get("/").text
        + client.get("/static/app.css").text
        + client.get("/static/app.js").text
    )


@pytest.fixture(autouse=True, scope="session")
def disable_rate_limits():
    """Set limiter.enabled = False for the entire test session."""
    from coursemap.api.server import limiter
    limiter.enabled = False
    yield
    limiter.enabled = True
