import requests

API_URL = "https://search-api.swiftype.com/api/v1/public/engines/search.json"

ENGINE_KEY = "8gdyLPudn1LsT169k6g6"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0"
}


def search(payload):

    payload["engine_key"] = ENGINE_KEY

    r = requests.post(API_URL, json=payload, headers=HEADERS, timeout=30)

    r.raise_for_status()

    return r.json()