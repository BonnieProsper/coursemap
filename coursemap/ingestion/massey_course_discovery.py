import requests

BASE = "https://www.massey.ac.nz/study/courses/"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def generate_candidate_codes():

    for subject in range(100, 400):

        for level in range(1, 8):

            for index in range(1, 60):

                yield f"{subject}{level}{index:02d}"


def discover_valid_courses():

    valid = []

    for code in generate_candidate_codes():

        url = BASE + f"course-{code}/"

        try:

            r = requests.get(url, headers=HEADERS, timeout=10)

            if r.status_code == 200:

                valid.append((code, url))
                print("FOUND", code)

        except Exception:
            pass

    return valid


if __name__ == "__main__":

    courses = discover_valid_courses()

    print("\nTotal discovered:", len(courses))