import re
import requests
from bs4 import BeautifulSoup


def scrape_prerequisites(url):

    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    text = soup.get_text(" ", strip=True)

    prereq_line = None

    for sentence in text.split("."):
        if "Prerequisite" in sentence:
            prereq_line = sentence
            break

    if not prereq_line:
        return []

    return re.findall(r"\b\d{6}\b", prereq_line)