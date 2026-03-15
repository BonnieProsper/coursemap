import os
import requests

API_URL = "https://search-api.swiftype.com/api/v1/public/engines/search.json"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
}


def search(payload: dict) -> dict:
    """Run a search against the Massey Swiftype API. Requires SWIFTYPE_ENGINE_KEY env var."""
    engine_key = os.environ.get("SWIFTYPE_ENGINE_KEY")
    if not engine_key:
        raise ValueError(
            "SWIFTYPE_ENGINE_KEY environment variable is not set. "
            "Set it to your Swiftype engine key to use the search API."
        )
    payload = {**payload, "engine_key": engine_key}
    r = requests.post(API_URL, json=payload, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()