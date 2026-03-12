import json
from coursemap.ingestion.scrape_majors import scrape_majors


def main():
    majors = scrape_majors()

    with open("majors.json", "w") as f:
        json.dump(majors, f, indent=2)

    print("Saved majors.json")


if __name__ == "__main__":
    main()