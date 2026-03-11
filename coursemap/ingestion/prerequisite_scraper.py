import re
import requests
from bs4 import BeautifulSoup


COURSE_CODE_RE = r"\b\d{6}\b"


def scrape_prerequisites(url):

    try:

        r = requests.get(url, timeout=15)

        soup = BeautifulSoup(r.text, "html.parser")

        text = soup.get_text(" ", strip=True)

        matches = []

        for sentence in text.split("."):

            if "Prerequisite" in sentence:

                matches += re.findall(COURSE_CODE_RE, sentence)

        return sorted(set(matches))

    except Exception:

        return []