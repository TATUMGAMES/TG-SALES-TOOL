# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tg_sales.db.database import Database
from tg_sales.db.models import Snapshot
from tg_sales.domain.snapshots import (
    epoch_ms,
    is_snapshot_name,
    snapshot_name,
    unique_snapshot_name,
)
from tg_sales.services.snapshots import SnapshotError, SnapshotService

from .conftest import FakeClock

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
MOMENT = datetime(2026, 10, 26, 3, 30, tzinfo=UTC)


def test_snapshot_names() -> None:
    tokyo = ZoneInfo("Asia/Tokyo")
    name = snapshot_name(MOMENT, tokyo)
    assert name == f"dashboard_snapshot_2026-10-26_{epoch_ms(MOMENT)}.png"
    assert snapshot_name(MOMENT, ZoneInfo("America/Los_Angeles")).startswith(
        "dashboard_snapshot_2026-10-25_"
    )  # local date, UTC epoch
    taken = {name, snapshot_name(MOMENT, tokyo, offset_ms=1)}
    assert unique_snapshot_name(MOMENT, taken.__contains__, tokyo).endswith(
        f"_{epoch_ms(MOMENT) + 2}.png"
    )
    assert is_snapshot_name(name)
    for bad in ("../x.png", "dashboard_snapshot_2026-10-26_1.png", "evil.png", name + ".exe"):
        assert not is_snapshot_name(bad)


@pytest.fixture
def service(database: Database, tmp_path: Path) -> SnapshotService:
    return SnapshotService(database, tmp_path / "snapshots", zone=ZoneInfo("UTC"))


def test_save_list_export_delete(
    service: SnapshotService, clock: FakeClock, tmp_path: Path
) -> None:
    clock.set(MOMENT)
    first = service.save(PNG, {"period": "Last 30 days"}, width=800, height=600)
    clock.set(MOMENT)  # same millisecond: the name must not collide
    second = service.save(PNG, {"period": "Last 7 days"})
    assert first.file_name != second.file_name
    assert first.path.read_bytes() == PNG and second.path.is_file()
    assert {s.id for s in service.list()} == {first.id, second.id}
    listed = {s.id: s for s in service.list()}
    assert listed[first.id].filters == {"period": "Last 30 days"}
    assert (listed[first.id].width, listed[first.id].height) == (800, 600)
    assert listed[first.id].app_version

    target = tmp_path / "out" / "copy.png"
    service.export(first.id, target)
    assert target.read_bytes() == PNG
    with pytest.raises(FileExistsError):
        service.export(first.id, target)  # never overwritten without confirmation
    service.export(first.id, target, overwrite=True)

    service.delete(first.id)
    assert not first.path.exists()
    assert [s.id for s in service.list()] == [second.id]
    with pytest.raises(SnapshotError, match="no longer exists"):
        service.path(first.id)
    with pytest.raises(SnapshotError, match="not a PNG"):
        service.save(b"GIF89a", {})


def test_paths_outside_the_folder_are_refused(
    service: SnapshotService, database: Database, clock: FakeClock, tmp_path: Path
) -> None:
    outside = tmp_path / "important.png"
    outside.write_bytes(PNG)
    clock.set(MOMENT)
    with database.session() as session:
        row = Snapshot(
            relative_path="../important.png",
            filters={},
            generated_at_utc=MOMENT,
            app_version="x",
        )
        session.add(row)
        session.flush()
        bad_id = row.id
    info = next(s for s in service.list() if s.id == bad_id)
    assert not info.exists
    with pytest.raises(SnapshotError, match="not in the snapshots folder"):
        service.path(bad_id)
    service.delete(bad_id)  # removes the entry only
    assert outside.read_bytes() == PNG


def test_missing_file_is_reported(service: SnapshotService, clock: FakeClock) -> None:
    clock.set(MOMENT)
    info = service.save(PNG, {})
    info.path.unlink()
    assert not service.list()[0].exists
    with pytest.raises(SnapshotError, match="missing"):
        service.path(info.id)
    service.delete(info.id)
    assert service.list() == []
