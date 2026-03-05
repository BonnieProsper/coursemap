import json
from pathlib import Path

from .course_parser import parse_course


RAW_DIR = Path("raw_html")
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


def build_dataset():

    dataset = []

    for file in RAW_DIR.glob("*.html"):

        html = file.read_text(encoding="utf-8")

        parsed = parse_course(html)

        course_code = file.stem

        dataset.append({
            "code": course_code,
            **parsed
        })

    with open(DATA_DIR / "dataset.json", "w") as f:
        json.dump(dataset, f, indent=2)

    print("Dataset built.")