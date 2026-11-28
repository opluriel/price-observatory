import os
import uuid
from collections import Counter
from pathlib import Path

import psycopg
import pytest

from src import reference
from src.parse.ministry_pdf import region_matches
from src.reference import (apply_migrations, load_departments, load_districts, load_products,
                           load_regions, sync_reference)

DB_URL = os.environ.get("TEST_DATABASE_URL")
SCHEMA_SQL = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"


def test_schema_contains_no_hardcoded_reference_data():
    """Regions and products live in data/reference/*.csv. A schema.sql that still seeds them is an old copy."""
    sql = SCHEMA_SQL.read_text(encoding="utf-8").upper()
    assert "INSERT INTO REGION" not in sql and "INSERT INTO PRODUCT" not in sql, (
        "sql/schema.sql still contains hardcoded regions/products: replace it with the latest version "
        "(reference data is loaded from data/reference/*.csv by `python -m src.admin setup`)")


def test_official_counts():
    """14 districts, 31 regions (+ 2 autonomous districts at the same level), 111 departments."""
    districts, regions, departments = load_districts(), load_regions(), load_departments()
    assert len(districts) == 14
    assert Counter(r["kind"] for r in regions) == {"region": 31, "district_autonome": 2}
    assert len(departments) == 111
    assert len(load_products()) == 32


def test_hierarchy_is_complete():
    regions, departments = load_regions(), load_departments()
    assert all(any(d["region"] == r["name"] for d in departments) for r in regions)   # no empty region
    assert {r["district"] for r in regions} == {d["name"] for d in load_districts()}  # no empty district
    by_region = {r["name"]: {d["name"] for d in departments if d["region"] == r["name"]} for r in regions}
    assert by_region["Bélier"] == {"Didiévi", "Djékanou", "Tiébissou", "Toumodi"}
    assert {"Bonon", "Gohitafla"} <= by_region["Marahoué"]            # departments created in 2020
    assert "Ouellé" in by_region["Iffou"]
    assert by_region["District de Yamoussoukro"] == {"Yamoussoukro", "Attiégouakro"}
    assert by_region["District d'Abidjan"] == {"Abidjan"}


def test_every_region_seat_is_one_of_its_departments():
    regions, departments = load_regions(), load_departments()
    for r in regions:
        names = {d["name"] for d in departments if d["region"] == r["name"]}
        assert r["main_city"] in names, r["name"]


def test_nested_keywords_do_not_make_headers_ambiguous():
    assert region_matches("HAUT SASSANDRA (Daloa)") == {"Haut-Sassandra"}
    assert region_matches("GBÔKLÉ (Sassandra - Fresco)") == {"Gbôklé"}


def test_duplicate_keyword_is_rejected(tmp_path, monkeypatch):
    for name in ("districts.csv", "departments.csv", "products.csv"):
        (tmp_path / name).write_text((reference.REFERENCE_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "regions.csv").write_text(
        "name,kind,district,main_city,keywords\nA,region,Lacs,a,xx\nB,region,Lacs,b,xx|yy\n", encoding="utf-8")
    monkeypatch.setattr(reference, "REFERENCE_DIR", tmp_path)
    with pytest.raises(ValueError, match="duplicate region keywords"):
        load_regions()


def test_department_pointing_to_unknown_region_is_rejected(tmp_path, monkeypatch):
    for name in ("districts.csv", "regions.csv", "products.csv"):
        (tmp_path / name).write_text((reference.REFERENCE_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "departments.csv").write_text("name,region\nNullepart,Région Fantôme\n", encoding="utf-8")
    monkeypatch.setattr(reference, "REFERENCE_DIR", tmp_path)
    with pytest.raises(ValueError, match="unknown regions"):
        load_departments()


@pytest.fixture()
def db():
    schema = "test_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DB_URL, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
    conn = psycopg.connect(DB_URL, options=f"-c search_path={schema}")
    conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.commit()
    yield conn
    conn.close()
    with psycopg.connect(DB_URL, autocommit=True) as admin:
        admin.execute(f"DROP SCHEMA {schema} CASCADE")


needs_db = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


@needs_db
def test_migrations_are_idempotent(db):
    first = apply_migrations(db)
    assert apply_migrations(db) == first and first


@needs_db
def test_sync_loads_the_whole_hierarchy_and_is_idempotent(db):
    apply_migrations(db)
    first = sync_reference(db)
    assert first == {"districts_added": 14, "regions_added": 33, "departments_added": 111, "products_added": 32}
    again = sync_reference(db)
    assert again == {"districts_added": 0, "regions_added": 0, "departments_added": 0, "products_added": 0}
    # the hierarchy can be navigated in SQL
    rows = db.execute("""SELECT dist.name, r.name, count(*) FROM department dp
                         JOIN region r ON r.id = dp.region_id JOIN district dist ON dist.id = r.district_id
                         WHERE r.name = 'Bélier' GROUP BY 1, 2""").fetchall()
    assert rows == [("Lacs", "Bélier", 4)]


@needs_db
def test_sync_upgrades_a_database_created_before_the_hierarchy(db):
    """Real case: a database already in service, with old regions that have no district."""
    apply_migrations(db)
    db.execute("INSERT INTO region (country_code, name, main_city) VALUES ('CI', 'Gbêkê', 'Bouaké') "
               "ON CONFLICT DO NOTHING")
    db.commit()
    result = sync_reference(db)
    assert result["regions_added"] == 32                       # Gbêkê already existed: updated, not duplicated
    assert db.execute("SELECT count(*) FROM region WHERE name = 'Gbêkê'").fetchone()[0] == 1
    assert db.execute("SELECT d.name FROM region r JOIN district d ON d.id = r.district_id "
                      "WHERE r.name = 'Gbêkê'").fetchone()[0] == "Vallée du Bandama"


def test_missing_migrations_stop_the_setup_instead_of_failing_later(tmp_path, monkeypatch):
    """Regression: without migration files the setup must stop with a clear message."""
    monkeypatch.setattr(reference, "MIGRATIONS_DIR", tmp_path / "absent")
    with pytest.raises(FileNotFoundError, match="No migration found"):
        apply_migrations(conn=None)
