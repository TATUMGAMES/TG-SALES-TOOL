# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Background jobs for slow work (imports, discovery, reports, sync, backups).

A job runs on a small worker pool, reports progress (percent and a short
message), can be cancelled cooperatively through a :class:`CancelToken`, and
keeps its result (or a user-facing error) for a while so the browser can poll
``GET /api/jobs/{id}``. Nothing here is specific to one feature.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from tg_sales.cancellation import CancelToken, OperationCancelledError
from tg_sales.domain.ids import new_id
from tg_sales.errors import TgSalesError

logger = logging.getLogger(__name__)

KEEP_FINISHED_SECONDS = 3600
MAX_WORKERS = 3

Progress = Callable[[int, str], None]
Work = Callable[[CancelToken, Progress], Any]


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    kind: str
    status: JobStatus = JobStatus.QUEUED
    percent: int = 0
    message: str = ""
    result: Any = None
    error: dict[str, str] | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    token: CancelToken = field(default_factory=CancelToken, repr=False)

    @property
    def done(self) -> bool:
        return self.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


class JobManager:
    def __init__(self, workers: int = MAX_WORKERS) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tg_sales_job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, work: Work, *, exclusive: bool = False) -> Job:
        """Start ``work``; ``exclusive`` refuses a second running job of the same kind."""
        with self._lock:
            self._expire()
            if exclusive and any(j.kind == kind and not j.done for j in self._jobs.values()):
                raise TgSalesError(
                    "This task is already running.",
                    action="Wait for it to finish, or cancel it first.",
                )
            job = Job(id=new_id(), kind=kind)
            self._jobs[job.id] = job
        self._pool.submit(self._run, job, work)
        return job

    def _run(self, job: Job, work: Work) -> None:
        def progress(percent: int, message: str) -> None:
            job.token.raise_if_cancelled()
            job.percent = max(0, min(100, int(percent)))
            job.message = message

        job.status = JobStatus.RUNNING
        try:
            job.result = work(job.token, progress)
            job.status = JobStatus.SUCCEEDED
            job.percent = 100
        except OperationCancelledError:
            job.status = JobStatus.CANCELLED
            job.message = "Cancelled. Nothing was saved."
        except TgSalesError as exc:
            job.status = JobStatus.FAILED
            job.error = {"message": exc.user_message, "action": exc.suggested_action}
            logger.warning(
                "Job failed", extra={"context": {"kind": job.kind, "detail": exc.detail}}
            )
        except Exception:
            job.status = JobStatus.FAILED
            job.error = {
                "message": "Something went wrong while doing this.",
                "action": "Try again. If it keeps happening, send the tg_sales log file to "
                "your support contact.",
            }
            logger.exception("Job crashed", extra={"context": {"kind": job.kind}})
        finally:
            job.finished_at = time.time()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.done:
            return False
        job.token.cancel()
        return True

    def _expire(self) -> None:
        cutoff = time.time() - KEEP_FINISHED_SECONDS
        for job_id in [
            j.id for j in self._jobs.values() if j.finished_at and j.finished_at < cutoff
        ]:
            del self._jobs[job_id]

    def shutdown(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.token.cancel()
        self._pool.shutdown(wait=True, cancel_futures=True)
