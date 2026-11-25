from datetime import date
from pathlib import Path

from src.pipeline import process_week, recent_weeks, run


def test_recent_weeks_only_returns_finished_weeks():
    # mercredi 25 nov. 2026 : la dernière semaine terminée est celle du 16 au 22 nov.
    assert recent_weeks(date(2026, 11, 25), 3) == [date(2026, 11, 2), date(2026, 11, 9), date(2026, 11, 16)]


def test_one_failing_week_does_not_stop_the_others():
    def download(monday, dest):
        return None if monday == date(2026, 6, 1) else Path(f"{monday}.pdf")

    def load(path, conn):
        if "06-15" in str(path):
            raise RuntimeError("Extraction à vérifier\ndétails...")
        return {"status": "success", "rows": 500}

    weeks = [date(2026, 6, 1), date(2026, 6, 8), date(2026, 6, 15)]
    results = run(weeks, conn=None, download=download, load=load)
    assert [r["status"] for r in results] == ["not_found", "success", "failed"]
    assert results[2]["detail"] == "Extraction à vérifier"
    assert process_week(weeks[1], None, download=download, load=load)["rows"] == 500
