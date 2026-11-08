"""Create a sync package from a simulated colleague's computer (for the browser tests).

    python tests/e2e_make_package.py --admin-url URL --out DIR
Prints the package path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from tg_sales.db.database import Database  # noqa: E402
from tg_sales.domain.ids import new_id  # noqa: E402
from tg_sales.domain.prospects import ContactDraft, OrganizationDraft  # noqa: E402
from tg_sales.services.identity import ensure_local_actor  # noqa: E402
from tg_sales.services.prospects import ProspectService  # noqa: E402
from tg_sales.sync.engine import SyncService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-url", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    admin = make_url(args.admin_url)
    name = f"tg_colleague_{new_id()[-8:]}"
    with psycopg.connect(
        host=admin.host,
        port=admin.port,
        user=admin.username,
        password=admin.password,
        dbname="postgres",
        autocommit=True,
    ) as connection:
        connection.execute(f'CREATE DATABASE "{name}" TEMPLATE tg_test_template')
    database = Database.open(admin.set(database=name))
    try:
        actor = ensure_local_actor(database)
        ProspectService(database, actor).create(
            OrganizationDraft("Colleague Games", website="colleague-games.example"),
            [ContactDraft(name="Robin", email="robin@colleague-games.example")],
        )
        result = SyncService(database, actor, lambda: "Colleague").export(Path(args.out))
        sys.stdout.write(str(result.path) + "\n")
    finally:
        database.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
