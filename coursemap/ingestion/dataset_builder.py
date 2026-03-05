import json
from pathlib import Path

from .parsers import parse_course


def build_dataset():

    dataset = []

    for file in Path("raw_html").glob("*.html"):

        html = file.read_text(encoding="utf-8")
        parsed = parse_course(html)

        code = file.stem

        dataset.append({
            "code": code,
            **parsed
        })

    with open("data/dataset.json", "w") as f:
        json.dump(dataset, f, indent=2)