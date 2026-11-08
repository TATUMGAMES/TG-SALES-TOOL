"""Import jobs and the per-record change log used to undo imports."""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tg_sales.db.models import ImportChange, ImportJob

STATUS_COMMITTED = "committed"
STATUS_UNDONE = "undone"

ACTION_CREATED = "created"
ACTION_UPDATED = "updated"


class ImportRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, job_id: str) -> ImportJob | None:
        job = self._session.get(ImportJob, job_id)
        return None if job is None or job.is_deleted else job

    def add(self, job: ImportJob) -> ImportJob:
        self._session.add(job)
        self._session.flush()
        return job

    def add_change(self, change: ImportChange) -> None:
        self._session.add(change)

    def defer_foreign_keys(self) -> None:
        """Check foreign keys at COMMIT instead of per statement, for this transaction only.

        Lets an import insert its rows in one batch in any order; a violation
        still makes the commit fail and roll back. (All foreign keys are declared
        DEFERRABLE INITIALLY IMMEDIATE.)
        """
        self._session.execute(text("SET CONSTRAINTS ALL DEFERRED"))

    def recent(self, limit: int = 100) -> list[ImportJob]:
        return list(
            self._session.scalars(
                select(ImportJob)
                .where(ImportJob.deleted_at_utc.is_(None))
                .order_by(ImportJob.started_at_utc.desc(), ImportJob.id.desc())
                .limit(limit)
            )
        )

    def committed_with_hash(self, file_sha256: str) -> list[ImportJob]:
        return list(
            self._session.scalars(
                select(ImportJob)
                .where(
                    ImportJob.file_sha256 == file_sha256,
                    ImportJob.status == STATUS_COMMITTED,
                    ImportJob.deleted_at_utc.is_(None),
                )
                .order_by(ImportJob.started_at_utc.desc())
            )
        )

    def changes(self, job_id: str) -> list[ImportChange]:
        """Changes made by a job, in the order they were made."""
        return list(
            self._session.scalars(
                select(ImportChange)
                .where(ImportChange.import_job_id == job_id, ImportChange.deleted_at_utc.is_(None))
                .order_by(ImportChange.created_at_utc, ImportChange.id)
            )
        )

    def known_fingerprints(self, fingerprints: Collection[str]) -> dict[str, tuple[str, str]]:
        """Map fingerprints already imported by active jobs to (organization id, job id)."""
        if not fingerprints:
            return {}
        rows = self._session.execute(
            select(ImportChange.row_fingerprint, ImportChange.entity_id, ImportJob.id)
            .join(ImportJob, ImportJob.id == ImportChange.import_job_id)
            .where(
                ImportChange.row_fingerprint.in_(list(fingerprints)),
                ImportChange.entity_table == "organizations",
                ImportChange.deleted_at_utc.is_(None),
                ImportJob.status == STATUS_COMMITTED,
            )
        )
        return {str(fp): (entity_id, job_id) for fp, entity_id, job_id in rows}

    def created_by(self, entity_id: str) -> ImportJob | None:
        """The active import that created ``entity_id``, if any."""
        return self._session.scalar(
            select(ImportJob)
            .join(ImportChange, ImportChange.import_job_id == ImportJob.id)
            .where(
                ImportChange.entity_id == entity_id,
                ImportChange.action == ACTION_CREATED,
                ImportJob.status == STATUS_COMMITTED,
            )
            .limit(1)
        )
