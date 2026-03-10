import json
from coursemap.ingestion.massey_course_search import discover_courses


def build_dataset():

    courses = discover_courses()

    with open("datasets/courses.json", "w", encoding="utf8") as f:
        json.dump(courses, f, indent=2)

    print("Saved", len(courses), "courses")


if __name__ == "__main__":
    build_dataset()