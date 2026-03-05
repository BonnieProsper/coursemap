import requests
from pathlib import Path
import time

BASE_URL = "https://www.massey.ac.nz/study/courses/"

RAW_DIR = Path("raw_html")
RAW_DIR.mkdir(exist_ok=True)


def download_course_page(course_id: str):
    url = f"{BASE_URL}{course_id}/"

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()

        path = RAW_DIR / f"{course_id}.html"

        with open(path, "w", encoding="utf-8") as f:
            f.write(r.text)

        print(f"Downloaded {course_id}")

        time.sleep(0.5)  # be polite to server

    except Exception as e:
        print(f"Failed {course_id}: {e}")