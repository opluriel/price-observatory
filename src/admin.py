"""Commandes d'administration.

    python -m src.admin migrate   # applique les migrations SQL (structure)
    python -m src.admin sync      # aligne la base sur data/reference/*.csv (données de référence)
    python -m src.admin setup     # migrate + sync (à utiliser en cas de doute)
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
        sys.exit("DATABASE_URL manquante (voir .env.example)")
    command = sys.argv[1]
    with psycopg.connect(url) as conn:
        if command in ("migrate", "setup"):
            print("Migrations appliquées :", ", ".join(apply_migrations(conn)))
        if command in ("sync", "setup"):
            for key, value in sync_reference(conn).items():
                print(f"{key:<18} {value}")


if __name__ == "__main__":
    main()
