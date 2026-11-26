"""Référentiels : source unique = fichiers CSV versionnés dans data/reference/.

    districts.csv     14 districts (12 districts + 2 districts autonomes)
    regions.csv       33 zones : 31 régions + les 2 districts autonomes d'Abidjan et de Yamoussoukro
    departments.csv   111 départements (depuis 2020), chacun rattaché à sa région
    products.csv      produits suivis

Ajouter une ligne dans un CSV, puis lancer  python -m src.admin setup.
Le parseur lit ces mêmes fichiers : plus aucune liste à modifier dans le code.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = ROOT / "data" / "reference"
MIGRATIONS_DIR = ROOT / "sql" / "migrations"
COUNTRY = "CI"


def _read(filename: str) -> list[dict]:
    with open(REFERENCE_DIR / filename, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _check_unique(values: list[str], what: str) -> None:
    seen: dict[str, int] = {}
    for v in values:
        seen[v] = seen.get(v, 0) + 1
    duplicates = sorted(v for v, n in seen.items() if n > 1)
    if duplicates:
        raise ValueError(f"Référentiel invalide : {what} en double {duplicates}")


def load_districts() -> list[dict]:
    rows = _read("districts.csv")
    _check_unique([r["name"] for r in rows], "districts")
    return rows


def load_regions() -> list[dict]:
    rows = _read("regions.csv")
    for row in rows:
        row["keywords"] = [k for k in row["keywords"].split("|") if k]
    _check_unique([r["name"] for r in rows], "régions")
    _check_unique([k for r in rows for k in r["keywords"]], "mots-clés de région")
    districts = {d["name"] for d in load_districts()}
    unknown = sorted({r["district"] for r in rows} - districts)
    if unknown:
        raise ValueError(f"Référentiel invalide : districts inconnus dans regions.csv {unknown}")
    return rows


def load_departments() -> list[dict]:
    rows = _read("departments.csv")
    _check_unique([r["name"] for r in rows], "départements")
    regions = {r["name"] for r in load_regions()}
    unknown = sorted({r["region"] for r in rows} - regions)
    if unknown:
        raise ValueError(f"Référentiel invalide : régions inconnues dans departments.csv {unknown}")
    return rows


def load_products() -> list[dict]:
    rows = _read("products.csv")
    for row in rows:
        row["prefixes"] = [p for p in row["prefixes"].split("|") if p]
    _check_unique([r["name"] for r in rows], "produits")
    _check_unique([p for r in rows for p in r["prefixes"]], "préfixes de produit")
    return rows


def apply_migrations(conn) -> list[str]:
    """Applique les fichiers sql/migrations/*.sql dans l'ordre (tous sont idempotents)."""
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.execute(path.read_text(encoding="utf-8"))
        applied.append(path.name)
    conn.commit()
    return applied


def sync_reference(conn) -> dict:
    """Aligne la base sur les CSV : ajoute ou met à jour, ne supprime jamais."""
    counts: dict[str, int] = {}

    def bump(key: str, inserted: bool) -> None:
        counts[key] = counts.get(key, 0) + 1 if inserted else counts.get(key, 0)

    with conn.cursor() as cur:
        for d in load_districts():
            cur.execute("""INSERT INTO district (country_code, name) VALUES (%s, %s)
                           ON CONFLICT (country_code, name) DO UPDATE SET name = EXCLUDED.name
                           RETURNING (xmax = 0)""", (COUNTRY, d["name"]))
            bump("districts_added", cur.fetchone()[0])
        cur.execute("SELECT name, id FROM district WHERE country_code = %s", (COUNTRY,))
        district_ids = dict(cur.fetchall())

        for r in load_regions():
            cur.execute("""INSERT INTO region (country_code, name, main_city, kind, district_id)
                           VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT (country_code, name) DO UPDATE
                             SET main_city = EXCLUDED.main_city, kind = EXCLUDED.kind,
                                 district_id = EXCLUDED.district_id
                           RETURNING (xmax = 0)""",
                        (COUNTRY, r["name"], r["main_city"], r["kind"], district_ids[r["district"]]))
            bump("regions_added", cur.fetchone()[0])
        cur.execute("SELECT name, id FROM region WHERE country_code = %s", (COUNTRY,))
        region_ids = dict(cur.fetchall())

        for d in load_departments():
            cur.execute("""INSERT INTO department (region_id, name) VALUES (%s, %s)
                           ON CONFLICT (name) DO UPDATE SET region_id = EXCLUDED.region_id
                           RETURNING (xmax = 0)""", (region_ids[d["region"]], d["name"]))
            bump("departments_added", cur.fetchone()[0])

        for p in load_products():
            cur.execute("""INSERT INTO product (name, category, unit) VALUES (%s, %s, %s)
                           ON CONFLICT (name) DO UPDATE SET category = EXCLUDED.category, unit = EXCLUDED.unit
                           RETURNING (xmax = 0)""", (p["name"], p["category"], p["unit"]))
            bump("products_added", cur.fetchone()[0])
    conn.commit()
    for key in ("districts_added", "regions_added", "departments_added", "products_added"):
        counts.setdefault(key, 0)
    return counts
