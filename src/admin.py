"""Administrative commands.

    python -m src.admin migrate   # applies SQL migrations (structure)
    python -m src.admin sync      # aligns the database with data/reference/*.csv (reference data)
    python -m src.admin setup     # migrate + sync (to use in case of doubt)
"""
import os
import sys

import psycopg
from dotenv import load_dotenv

from src.reference import apply_migrations, sync_reference

COMMANDS = {"migrate", "sync", "setup"}


def main() -> None:
    load_dotenv()
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit("Usage : python -m src.admin migrate | sync | setup")
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL missing (see .env.example)")
    command = sys.argv[1]
    with psycopg.connect(url) as conn:
        if command in ("migrate", "setup"):
            print("Migrations applied :", ", ".join(apply_migrations(conn)))
        if command in ("sync", "setup"):
            for key, value in sync_reference(conn).items():
                print(f"{key:<18} {value}")


if __name__ == "__main__":
    main()
