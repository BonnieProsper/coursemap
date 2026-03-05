import requests
from pathlib import Path

BASE_URL = "https://www.massey.ac.nz/courses/"


def download_course_page(code: str):
    url = f"{BASE_URL}{code.lower()}/"

    r = requests.get(url, timeout=10)
    r.raise_for_status()

    path = Path("raw_html")
    path.mkdir(exist_ok=True)

    with open(path / f"{code}.html", "w", encoding="utf-8") as f:
        f.write(r.text)