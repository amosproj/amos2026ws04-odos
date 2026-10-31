"""Bounded in-process worker for local development.

One worker thread by default and a capped number of waiting jobs. State is
persisted in each document's meta.json. Not a distributed queue: jobs do not
survive a server restart (interrupted jobs are marked failed on startup).
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from odos.api.schemas import JobStatus
from odos.api.storage import Store
from odos.pipeline import PipelineResult, ProcessingMode

PipelineFn = Callable[..., PipelineResult]


class QueueFull(Exception):
    pass


class JobManager:
    def __init__(self, store: Store, pipeline: PipelineFn, workers: int = 1, max_queue: int = 8):
        self.store, self.pipeline = store, pipeline
        self.max_queue = max_queue
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="odos-job")
        self._pending = 0
        self._lock = threading.Lock()
        self._recover()

    def _recover(self) -> None:
        for st in self.store.list():
            if st.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
                self.store.update(st.id, status=JobStatus.FAILED, stage=None, finished_at=_now(),
                                  error="Processing was interrupted by a server restart. Start it again.")  # fmt: skip

    def submit(self, doc_id: str, mode: ProcessingMode) -> None:
        with self._lock:
            if self._pending >= self.max_queue:
                raise QueueFull
            self._pending += 1
        self.store.clear_outputs(doc_id)
        self.store.update(doc_id, status=JobStatus.QUEUED, stage="queued", mode=mode, outcome=None, message=None,
                          error=None, summary={}, started_at=None, finished_at=None, routing=None)  # fmt: skip
        self._pool.submit(self._run, doc_id, mode)

    def _run(self, doc_id: str, mode: ProcessingMode) -> None:
        try:
            st = self.store.update(doc_id, status=JobStatus.PROCESSING, stage="starting", started_at=_now())
            res = self.pipeline(
                self.store.original(doc_id), self.store.output_dir(doc_id), mode, st.uploaded_at.date().isoformat(),
                progress=lambda stage: self.store.update(doc_id, stage=stage),
            )  # fmt: skip
            self.store.update(doc_id, status=JobStatus.COMPLETED, stage=None, outcome=res.outcome, message=res.message,
                              summary=res.summary, finished_at=_now())  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - any failure must surface as a failed job
            traceback.print_exc()
            self.store.update(doc_id, status=JobStatus.FAILED, stage=None, finished_at=_now(),
                              error=f"{type(exc).__name__}: {exc}"[:1000])  # fmt: skip
        finally:
            with self._lock:
                self._pending -= 1

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)
