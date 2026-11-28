"""Reference data (districts, regions, departments, products) stored as versioned CSV files.

Single source of truth, kept in ``data/reference/``:

    districts.csv     14 districts (12 districts + 2 autonomous districts)
    regions.csv       33 zones: 31 regions + the autonomous districts of Abidjan and Yamoussoukro
    departments.csv   111 departments (since 2020), each linked to its region
    products.csv      tracked products

To add a row, edit the relevant CSV file and run ``python -m src.admin setup``.
The PDF parser reads the same files, so no list needs to be edited in the code.
"""

import csv
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = ROOT / "data" / "reference"
MIGRATIONS_DIR = ROOT / "sql" / "migrations"
COUNTRY = "CI"


def _read(filename: str) -> list[dict[str, Any]]:
    with (REFERENCE_DIR / filename).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _split(value: str) -> list[str]:
    """Split a pipe-separated CSV cell into its non-empty items."""
    return [item for item in value.split("|") if item]


def _check_unique(values: Iterable[str], what: str) -> None:
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        raise ValueError(f"Invalid reference data: duplicate {what} {duplicates}")


def load_districts() -> list[dict[str, Any]]:
    rows = _read("districts.csv")
    _check_unique((row["name"] for row in rows), "districts")
    return rows


def load_regions() -> list[dict[str, Any]]:
    rows = _read("regions.csv")
    for row in rows:
        row["keywords"] = _split(row["keywords"])
    _check_unique((row["name"] for row in rows), "regions")
    _check_unique((keyword for row in rows for keyword in row["keywords"]), "region keywords")
    unknown = sorted({row["district"] for row in rows} - {d["name"] for d in load_districts()})
    if unknown:
        raise ValueError(f"Invalid reference data: unknown districts in regions.csv {unknown}")
    return rows


def load_departments() -> list[dict[str, Any]]:
    rows = _read("departments.csv")
    _check_unique((row["name"] for row in rows), "departments")
    unknown = sorted({row["region"] for row in rows} - {r["name"] for r in load_regions()})
    if unknown:
        raise ValueError(f"Invalid reference data: unknown regions in departments.csv {unknown}")
    return rows


def load_products() -> list[dict[str, Any]]:
    rows = _read("products.csv")
    for row in rows:
        row["prefixes"] = _split(row["prefixes"])
    _check_unique((row["name"] for row in rows), "products")
    _check_unique((prefix for row in rows for prefix in row["prefixes"]), "product prefixes")
    return rows


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply every ``sql/migrations/*.sql`` file in order, in a single transaction.

    All migrations are idempotent, so running them again is safe.
    Raises ``FileNotFoundError`` when no migration exists, rather than silently doing nothing.
    """
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise FileNotFoundError(
            f"No migration found in {MIGRATIONS_DIR}: create this directory and copy the .sql files into it."
        )
    with conn.transaction():
        for path in files:
            conn.execute(path.read_text(encoding="utf-8"))
    conn.commit()
    return [path.name for path in files]


def _upsert(cur: psycopg.Cursor, query: str, params: tuple[Any, ...]) -> bool:
    """Run an ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING (xmax = 0)`` and report whether a row was inserted.

    ``xmax = 0`` is true for a freshly inserted row and false for an updated one (PostgreSQL system column).
    """
    cur.execute(query, params)
    row = cur.fetchone()
    return bool(row and row[0])


def sync_reference(conn: psycopg.Connection) -> dict[str, int]:
    """Align the database with the CSV files: insert or update rows, never delete.

    All statements are parameterised and run in one transaction: either everything is synced or nothing is.
    """
    counts = Counter(districts_added=0, regions_added=0, departments_added=0, products_added=0)

    with conn.transaction(), conn.cursor() as cur:
        for district in load_districts():
            if _upsert(
                cur,
                """INSERT INTO district (country_code, name) VALUES (%s, %s)
                   ON CONFLICT (country_code, name) DO UPDATE SET name = EXCLUDED.name
                   RETURNING (xmax = 0)""",
                (COUNTRY, district["name"]),
            ):
                counts["districts_added"] += 1
        cur.execute("SELECT name, id FROM district WHERE country_code = %s", (COUNTRY,))
        district_ids = dict(cur.fetchall())

        for region in load_regions():
            if _upsert(
                cur,
                """INSERT INTO region (country_code, name, main_city, kind, district_id)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (country_code, name) DO UPDATE
                       SET main_city = EXCLUDED.main_city, kind = EXCLUDED.kind,
                           district_id = EXCLUDED.district_id
                   RETURNING (xmax = 0)""",
                (COUNTRY, region["name"], region["main_city"], region["kind"], district_ids[region["district"]]),
            ):
                counts["regions_added"] += 1
        cur.execute("SELECT name, id FROM region WHERE country_code = %s", (COUNTRY,))
        region_ids = dict(cur.fetchall())

        for department in load_departments():
            if _upsert(
                cur,
                """INSERT INTO department (region_id, name) VALUES (%s, %s)
                   ON CONFLICT (name) DO UPDATE SET region_id = EXCLUDED.region_id
                   RETURNING (xmax = 0)""",
                (region_ids[department["region"]], department["name"]),
            ):
                counts["departments_added"] += 1

        for product in load_products():
            if _upsert(
                cur,
                """INSERT INTO product (name, category, unit) VALUES (%s, %s, %s)
                   ON CONFLICT (name) DO UPDATE SET category = EXCLUDED.category, unit = EXCLUDED.unit
                   RETURNING (xmax = 0)""",
                (product["name"], product["category"], product["unit"]),
            ):
                counts["products_added"] += 1

    conn.commit()
    return dict(counts)
