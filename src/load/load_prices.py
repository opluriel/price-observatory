"""Upload a weekly PDF from the ministry to PostgreSQL.

Guarantees:
- idempotent: the same file (same SHA-256 hash) is never loaded twice;
- atomic: the entire file is loaded, or nothing;
- traceable: each attempt leaves a row in ingestion_run (success / failed / skipped).

Usage :
    python -m src.load.load_prices data/raw/PRIX_A_LA_CONSOMMATION_01_06_AU_07_06_2026.pdf
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

from src.parse.ministry_pdf import parse_pdf
from src.quality.checks import flag_quality

SOURCE_CODE = "ci_commerce_weekly"
COUNTRY = "CI"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _none_if_nan(value):
    return None if pd.isna(value) else int(value)


def load_file(pdf_path: str | Path, conn: psycopg.Connection) -> dict:
    pdf_path = Path(pdf_path)
    digest = sha256_of(pdf_path)

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM source WHERE code = %s", (SOURCE_CODE,))
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"Source « {SOURCE_CODE} » absente : exécute d'abord sql/schema.sql")
        source_id = row[0]

        cur.execute("SELECT id FROM ingestion_run WHERE source_id = %s AND file_sha256 = %s AND status = 'success'",
                    (source_id, digest))
        if cur.fetchone():
            cur.execute("INSERT INTO ingestion_run (source_id, file_url, file_sha256, status, rows_loaded) "
                        "VALUES (%s, %s, %s, 'skipped', 0)", (source_id, pdf_path.name, digest))
            conn.commit()
            return {"status": "skipped", "rows": 0, "reason": "fichier déjà chargé"}

    df, report = parse_pdf(pdf_path)
    if not report.ok():
        raise RuntimeError("Extraction à vérifier : " + " ; ".join(report.problems()) + "\n" + report.summary())
    df = flag_quality(df)

    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO ingestion_run (source_id, file_url, file_sha256) VALUES (%s, %s, %s) "
                        "RETURNING id", (source_id, pdf_path.name, digest))
            run_id = cur.fetchone()[0]

            cur.execute("SELECT name, id FROM region WHERE country_code = %s", (COUNTRY,))
            regions = dict(cur.fetchall())
            cur.execute("SELECT name, id FROM product")
            products = dict(cur.fetchall())

            missing = (set(df["region"]) - set(regions)) | (set(df["product"]) - set(products))
            if missing:
                raise RuntimeError(f"Référentiel incomplet, valeurs absentes de la base : {sorted(missing)}")

            rows = [(run_id, source_id, products[r.product], regions[r.region], r.period_start, r.period_end,
                     _none_if_nan(r.price_min), _none_if_nan(r.price_max), _none_if_nan(r.price_avg),
                     r.quality_flag) for r in df.itertuples()]
            cur.executemany(
                """INSERT INTO price_observation
                     (run_id, source_id, product_id, region_id, period_start, period_end,
                      price_min, price_max, price_avg, quality_flag)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (source_id, product_id, region_id, period_start, period_end)
                   DO UPDATE SET run_id = EXCLUDED.run_id, price_min = EXCLUDED.price_min,
                                 price_max = EXCLUDED.price_max, price_avg = EXCLUDED.price_avg,
                                 quality_flag = EXCLUDED.quality_flag""", rows)
            cur.execute("UPDATE ingestion_run SET status = 'success', rows_loaded = %s WHERE id = %s",
                        (len(rows), run_id))
        conn.commit()
        return {"status": "success", "rows": len(rows), "flagged": int((df["quality_flag"] != "ok").sum()),
                "period": f"{report.period_start} -> {report.period_end}"}
    except Exception as exc:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO ingestion_run (source_id, file_url, file_sha256, status, error) "
                        "VALUES (%s, %s, %s, 'failed', %s)", (source_id, pdf_path.name, digest, str(exc)[:2000]))
        conn.commit()
        raise


def main() -> None:
    load_dotenv()
    if len(sys.argv) != 2:
        sys.exit("Usage : python -m src.load.load_prices chemin/vers/fichier.pdf")
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL manquante : copie .env.example en .env et renseigne ta chaîne de connexion.")
    with psycopg.connect(url) as conn:
        print(load_file(sys.argv[1], conn))


if __name__ == "__main__":
    main()
