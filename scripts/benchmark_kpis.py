"""Benchmark the dashboard and prospect search on a large synthetic PostgreSQL database.

Starts a throwaway PostgreSQL server (the portable runtime, as in the tests),
loads synthetic prospects (invented names on ``.example`` domains), contacts,
opportunities and a long activity history, then times dashboard calculations
(cold and cached) and prospect searches.

Usage (from the repository root):
    .venv\\Scripts\\python.exe scripts\\benchmark_kpis.py [contacts] [activities]

Defaults: 100,000 contacts and 500,000 activities. Everything lives in a
temporary folder that is deleted afterwards; the real data folder is never used.
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.pg import start_test_server  # noqa: E402

from tg_sales.db.database import Database  # noqa: E402
from tg_sales.domain.enums import ActivityType  # noqa: E402
from tg_sales.domain.ids import new_id  # noqa: E402
from tg_sales.domain.kpi import KpiFilters  # noqa: E402
from tg_sales.domain.periods import PeriodPreset, preset_range  # noqa: E402
from tg_sales.domain.prospects import ProspectQuery  # noqa: E402
from tg_sales.domain.stages import DEFAULT_STAGES  # noqa: E402
from tg_sales.services.identity import ensure_local_actor  # noqa: E402
from tg_sales.services.kpis import KpiService  # noqa: E402
from tg_sales.services.prospects import ProspectService  # noqa: E402

OUTREACH = [
    ActivityType.EMAIL,
    ActivityType.LINKEDIN_MESSAGE,
    ActivityType.PHONE_CALL,
    ActivityType.REPLY,
    ActivityType.PROPOSAL,
]
DEVICE = "00000000-0000-4000-8000-0000000be4c4"


def say(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def build(database: Database, contacts: int, activities: int) -> str:
    rng = random.Random(7)  # noqa: S311 - synthetic data, not security
    actor = ensure_local_actor(database)
    now = datetime.now(UTC)
    organizations = contacts // 2
    opportunities = organizations // 2
    org_ids = [new_id() for _ in range(organizations)]
    opp_ids = [new_id() for _ in range(opportunities)]
    contact_ids = [new_id() for _ in range(contacts)]
    stage_ids = [s.id for s in DEFAULT_STAGES]

    def when(days: float) -> datetime:
        return now - timedelta(days=days)

    url = database.url
    with (
        psycopg.connect(
            host=url.host,
            port=url.port,
            user=url.username,
            password=url.password,
            dbname=url.database,
        ) as connection,
        connection.cursor() as cursor,
    ):
        with cursor.copy(
            "COPY organizations (id, name, normalized_name, domain, company_type, source, tags, "
            "created_at_utc, updated_at_utc, created_by_device_id) FROM STDIN"
        ) as copy:
            for i, oid in enumerate(org_ids):
                copy.write_row(
                    (
                        oid,
                        f"Studio {i}",
                        f"studio {i}",
                        f"studio{i}.example",
                        "unknown",
                        "import",
                        "[]",
                        when(rng.uniform(0, 730)),
                        now,
                        DEVICE,
                    )
                )
        with cursor.copy(
            "COPY contacts (id, organization_id, name, business_email, email_normalized, "
            "social_urls, contact_status, source, created_at_utc, updated_at_utc, "
            "created_by_device_id) FROM STDIN"
        ) as copy:
            for i, cid in enumerate(contact_ids):
                email = f"person{i}@studio{i // 2}.example"
                copy.write_row(
                    (
                        cid,
                        org_ids[i // 2],
                        f"Person {i}",
                        email,
                        email,
                        "{}",
                        "unknown",
                        "import",
                        when(rng.uniform(0, 730)),
                        now,
                        DEVICE,
                    )
                )
        with cursor.copy(
            "COPY opportunities (id, organization_id, product_lane, stage_id, owner_actor_id, "
            "created_at_utc, updated_at_utc, created_by_device_id) FROM STDIN"
        ) as copy:
            for i, pid in enumerate(opp_ids):
                copy.write_row(
                    (
                        pid,
                        org_ids[i],
                        "data_licensing",
                        rng.choice(stage_ids[:7]),
                        actor,
                        when(700),
                        now,
                        DEVICE,
                    )
                )
        with cursor.copy(
            "COPY activities (id, occurred_at_utc, type, actor_id, organization_id, contact_id, "
            "opportunity_id, payload, source, created_at_utc, updated_at_utc, "
            "created_by_device_id) FROM STDIN"
        ) as copy:
            for _ in range(activities):
                i = rng.randrange(opportunities)
                kind = rng.choice([*OUTREACH, ActivityType.STAGE_CHANGE])
                payload: dict[str, str] = {}
                if kind is ActivityType.STAGE_CHANGE:
                    target = rng.choice(DEFAULT_STAGES)
                    payload = {"to_stage_id": target.id, "to_outcome": target.outcome.value}
                moment = when(rng.uniform(0, 730))
                copy.write_row(
                    (
                        new_id(),
                        moment,
                        kind.value,
                        actor,
                        org_ids[i],
                        contact_ids[2 * i],
                        opp_ids[i],
                        json.dumps(payload),
                        "import",
                        moment,
                        moment,
                        DEVICE,
                    )
                )
        connection.commit()
        cursor.execute("ANALYZE")
    return actor


def timed(label: str, action: object) -> float:
    started = time.perf_counter()
    action()  # type: ignore[operator]
    elapsed = time.perf_counter() - started
    say(f"{label:<44} {elapsed * 1000:8.0f} ms")
    return elapsed


def main() -> int:
    contacts = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    activities = int(sys.argv[2]) if len(sys.argv) > 2 else 500_000
    with tempfile.TemporaryDirectory() as tmp:
        server = start_test_server(Path(tmp))
        if server is None:
            say("PostgreSQL runtime not found; run scripts/setup_postgres.py first.")
            return 1
        try:
            database = Database.open(server.create_database())
            started = time.perf_counter()
            actor = build(database, contacts, activities)
            say(
                f"loaded {contacts:,} contacts / {contacts // 2:,} prospects / "
                f"{activities:,} activities in {time.perf_counter() - started:.1f}s"
            )
            kpis = KpiService(database)
            for preset in (
                PeriodPreset.LAST_7_DAYS,
                PeriodPreset.LAST_3_MONTHS,
                PeriodPreset.LAST_12_MONTHS,
            ):
                dates = preset_range(preset, kpis.today())
                timed(
                    f"dashboard {preset.value} (cold)",
                    lambda d=dates: kpis.dashboard(d, KpiFilters()),
                )
                timed(
                    f"dashboard {preset.value} (cached)",
                    lambda d=dates: kpis.dashboard(d, KpiFilters()),
                )
            prospects = ProspectService(database, actor)
            timed("prospect list, first page", lambda: prospects.search(ProspectQuery(limit=100)))
            timed(
                "prospect search 'studio 4321'",
                lambda: prospects.search(ProspectQuery("studio 4321", limit=100)),
            )
            timed(
                "prospect search by email domain",
                lambda: prospects.search(ProspectQuery("studio777.example", limit=100)),
            )
            timed(
                "prospect detail",
                lambda: prospects.get_detail(prospects.search(ProspectQuery(limit=1)).rows[0].id),
            )
            database.dispose()
        finally:
            server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
