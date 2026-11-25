from datetime import date

import requests

from src.collect.ministry_weekly import (RobotsCache, candidate_urls, download_week, filename_for,
                                         week_ranges)
from src.parse.ministry_pdf import parse_period


class Resp:
    def __init__(self, status=200, content=b"", text=""):
        self.status_code, self.content, self.text = status, content, text


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, timeout=None):
        self.calls.append(url)
        if url not in self.routes:
            return Resp(404)
        route = self.routes[url]
        if isinstance(route, Exception):
            raise route
        return route


MONDAY = date(2026, 6, 1)
NAME = "PRIX_A_LA_CONSOMMATION_01_06_AU_07_06_2026.pdf"
NO_WAIT = dict(delay=0, sleep=lambda s: None)


def test_filename_matches_ministry_convention_and_parser():
    assert filename_for(MONDAY) == NAME
    assert filename_for(date(2025, 12, 29)) == "PRIX_A_LA_CONSOMMATION_29_12_AU_04_01_2026.pdf"
    assert parse_period("", filename_for(date(2025, 12, 29))) == (date(2025, 12, 29), date(2026, 1, 4))


def test_week_ranges_are_monday_to_sunday():
    weeks = list(week_ranges(date(2026, 6, 3), date(2026, 6, 16)))   # mercredi -> mardi suivant+1
    assert weeks == [(date(2026, 6, 1), date(2026, 6, 7)), (date(2026, 6, 8), date(2026, 6, 14)),
                     (date(2026, 6, 15), date(2026, 6, 21))]


def test_downloads_from_second_host_when_first_is_missing(tmp_path):
    first, second = candidate_urls(NAME)
    session = FakeSession({second: Resp(200, b"%PDF-1.4 contenu")})
    path = download_week(MONDAY, tmp_path, session=session, **NO_WAIT)
    assert path == tmp_path / NAME and path.read_bytes().startswith(b"%PDF-")
    assert first in session.calls and second in session.calls


def test_html_error_page_is_not_saved_as_pdf(tmp_path):
    session = FakeSession({u: Resp(200, b"<html>Page introuvable</html>") for u in candidate_urls(NAME)})
    assert download_week(MONDAY, tmp_path, session=session, **NO_WAIT) is None
    assert not list(tmp_path.iterdir())


def test_existing_file_is_not_downloaded_again(tmp_path):
    (tmp_path / NAME).write_bytes(b"%PDF-deja la")
    session = FakeSession({})
    assert download_week(MONDAY, tmp_path, session=session, **NO_WAIT) == tmp_path / NAME
    assert session.calls == []


def test_robots_disallow_blocks_download(tmp_path):
    routes = {"https://www.economie-ivoirienne.ci/robots.txt": Resp(200, text="User-agent: *\nDisallow: /"),
              "https://www.ocpv-ci.com/robots.txt": Resp(200, text="User-agent: *\nDisallow: /"),
              **{u: Resp(200, b"%PDF-1.4") for u in candidate_urls(NAME)}}
    session = FakeSession(routes)
    assert download_week(MONDAY, tmp_path, session=session, **NO_WAIT) is None
    assert not [c for c in session.calls if c.endswith(".pdf")]


def test_network_error_is_survived(tmp_path):
    first, second = candidate_urls(NAME)
    session = FakeSession({first: requests.ConnectionError("boom"), second: Resp(200, b"%PDF-1.4")})
    assert download_week(MONDAY, tmp_path, session=session, **NO_WAIT) is not None


def test_robots_cache_reads_each_site_once():
    session = FakeSession({})
    robots = RobotsCache(session)
    url = candidate_urls(NAME)[0]
    assert robots.allowed(url) and robots.allowed(url)          # robots.txt absent (404) : autorisé
    assert session.calls.count("https://www.economie-ivoirienne.ci/robots.txt") == 1
