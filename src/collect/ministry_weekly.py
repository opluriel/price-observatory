"""Téléchargement des PDF hebdomadaires du ministère du Commerce (prix des produits vivriers).

Les fichiers suivent une convention de nommage stable : une semaine du lundi au dimanche, par ex.
PRIX_A_LA_CONSOMMATION_01_06_AU_07_06_2026.pdf. On calcule donc les adresses candidates au lieu de
« scraper » des pages HTML, sur deux hébergements publics du même document.

Bonnes pratiques : on lit robots.txt, on s'identifie, on espace les requêtes (2 s) et on ne
retélécharge jamais un fichier déjà présent.
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = "observatoire-prix-ci/0.1 (projet ouvert d'analyse des prix)"
URL_TEMPLATES = [
    "https://www.economie-ivoirienne.ci/sites/default/files/sites/default/files/inline-files/{name}",
    "https://www.ocpv-ci.com/doc/prix_consomation/{name}",
]
REQUEST_DELAY = 2.0  # secondes entre deux requêtes


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_ranges(start: date, end: date):
    """Semaines (lundi, dimanche) dont le lundi est compris entre le lundi de `start` et `end`."""
    monday = monday_of(start)
    while monday <= end:
        yield monday, monday + timedelta(days=6)
        monday += timedelta(days=7)


def filename_for(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    return f"PRIX_A_LA_CONSOMMATION_{monday:%d_%m}_AU_{sunday:%d_%m_%Y}.pdf"


def candidate_urls(name: str) -> list[str]:
    return [template.format(name=name) for template in URL_TEMPLATES]


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


class RobotsCache:
    """Lit robots.txt une fois par site. En cas de doute (erreur réseau, accès refusé) : on s'abstient."""

    def __init__(self, session):
        self.session = session
        self._parsers: dict[str, RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._parsers:
            parser = RobotFileParser()
            try:
                resp = self.session.get(base + "/robots.txt", timeout=15)
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                elif resp.status_code in (401, 403):
                    parser.disallow_all = True
                else:
                    parser.allow_all = True
            except requests.RequestException:
                parser.disallow_all = True
            self._parsers[base] = parser
        return self._parsers[base].can_fetch(USER_AGENT, url)


def download_week(monday: date, dest_dir: str | Path, session=None, robots=None,
                  delay: float = REQUEST_DELAY, sleep=time.sleep) -> Path | None:
    """Retourne le chemin du PDF de la semaine (déjà présent ou téléchargé), ou None s'il est introuvable."""
    target = Path(dest_dir) / filename_for(monday)
    if target.exists():
        return target
    session = session or make_session()
    robots = robots or RobotsCache(session)
    for url in candidate_urls(target.name):
        if not robots.allowed(url):
            continue
        sleep(delay)
        try:
            resp = session.get(url, timeout=30)
        except requests.RequestException:
            continue
        if resp.status_code == 200 and resp.content[:5] == b"%PDF-":   # une page d'erreur HTML n'est pas un PDF
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(resp.content)
            return target
    return None
