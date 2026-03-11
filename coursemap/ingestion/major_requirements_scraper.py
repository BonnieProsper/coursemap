import re
import requests
from bs4 import BeautifulSoup


COURSE_RE = r"\b\d{6}\b"


def scrape_major_requirements(url):

    r = requests.get(url)

    soup = BeautifulSoup(r.text, "html.parser")

    text = soup.get_text(" ", strip=True)

    codes = re.findall(COURSE_RE, text)

    return sorted(set(codes))