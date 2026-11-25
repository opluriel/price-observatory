"""Chaîne complète : télécharger les PDF hebdomadaires, les extraire, les charger en base.

Exemples :
    python -m src.pipeline --from 2026-01-05 --to 2026-06-01   # rattrapage de l'historique
    python -m src.pipeline --weeks-back 3                      # mode hebdomadaire (idempotent)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from src.collect.ministry_weekly import download_week, monday_of, week_ranges

RAW_DIR = Path("data/raw")


def recent_weeks(today: date, n: int) -> list[date]:
    """Les n derniers lundis de semaines TERMINÉES (la semaine en cours n'est pas encore publiée)."""
    last = monday_of(today - timedelta(days=7))
    return [last - timedelta(days=7 * k) for k in reversed(range(n))]


def process_week(monday: date, conn, dest_dir=RAW_DIR, download=download_week, load=None) -> dict:
    if load is None:
        from src.load.load_prices import load_file as load
    path = download(monday, dest_dir)
    if path is None:
        return {"week": monday, "status": "not_found"}
    try:
        return {"week": monday, **load(path, conn)}
    except Exception as exc:                      # une semaine en échec n'arrête pas les autres
        return {"week": monday, "status": "failed", "detail": str(exc).splitlines()[0][:400]}


def run(weeks: list[date], conn, **kwargs) -> list[dict]:
    results = []
    for monday in weeks:
        result = process_week(monday, conn, **kwargs)
        print(f"{monday}  {result['status']:<10} {result.get('rows', '')} {result.get('detail', '')}")
        results.append(result)
    return results


def main() -> None:
    import psycopg
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", type=date.fromisoformat)
    parser.add_argument("--to", dest="end", type=date.fromisoformat)
    parser.add_argument("--weeks-back", type=int, default=3)
    args = parser.parse_args()

    if args.start:
        weeks = [m for m, _ in week_ranges(args.start, args.end or date.today())]
    else:
        weeks = recent_weeks(date.today(), args.weeks_back)

    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL manquante (voir .env.example)")
    with psycopg.connect(url) as conn:
        results = run(weeks, conn)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("Bilan :", counts)


if __name__ == "__main__":
    main()
