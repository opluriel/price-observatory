"""Tests du chargeur sur un vrai PostgreSQL.

Ils tournent dans un schéma temporaire (supprimé à la fin) : aucune donnée existante n'est touchée.
Pour les lancer :  TEST_DATABASE_URL=postgresql://... python -m pytest tests/test_load_prices.py
"""
import os
import uuid
from pathlib import Path

import psycopg
import pytest

from src.load.load_prices import load_file
from src.parse import ministry_pdf
from src.reference import apply_migrations, sync_reference
from tests.make_fixture import build

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL non définie")
SCHEMA_SQL = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"


@pytest.fixture()
def conn(monkeypatch):
    monkeypatch.setattr(ministry_pdf, "MIN_REGIONS", 6)   # le PDF factice n'a que 6 départements
    schema = "test_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DB_URL, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
    c = psycopg.connect(DB_URL, options=f"-c search_path={schema}")
    c.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    c.commit()
    apply_migrations(c)
    sync_reference(c)
    yield c
    c.close()
    with psycopg.connect(DB_URL, autocommit=True) as admin:
        admin.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture()
def pdf(tmp_path):
    return build(tmp_path / "PRIX_A_LA_CONSOMMATION_01_06_AU_07_06_2026.pdf")


def count(conn, table, where="true"):
    return conn.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0]


def test_load_inserts_rows_and_keeps_flags(conn, pdf):
    result = load_file(pdf, conn)
    assert result["status"] == "success" and result["rows"] == 18
    assert count(conn, "price_observation") == 18
    assert count(conn, "price_observation", "quality_flag = 'suspect_outlier'") == 1
    assert count(conn, "ingestion_run", "status = 'success' AND rows_loaded = 18") == 1


def test_same_file_is_not_loaded_twice(conn, pdf):
    load_file(pdf, conn)
    again = load_file(pdf, conn)
    assert again["status"] == "skipped"
    assert count(conn, "price_observation") == 18
    assert count(conn, "ingestion_run", "status = 'skipped'") == 1


def test_failure_is_atomic_and_traced(conn, pdf):
    conn.execute("DELETE FROM product WHERE name = 'Gombo frais'")
    conn.commit()
    with pytest.raises(RuntimeError, match="Référentiel incomplet"):
        load_file(pdf, conn)
    assert count(conn, "price_observation") == 0
    assert count(conn, "ingestion_run", "status = 'failed'") == 1
