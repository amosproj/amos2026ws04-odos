"""Persistence for reviews. FileReviewStore is the local MVP; a database store can implement the same protocol."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from odos.review.model import Confirmation, Correction, ReviewRecord


class ReviewStore(Protocol):
    def load(self, doc_id: str) -> ReviewRecord | None: ...
    def save(self, doc_id: str, record: ReviewRecord, expected_revision: int | None) -> None: ...
    def corrections(self, doc_id: str) -> list[Correction]: ...
    def append_correction(self, doc_id: str, c: Correction) -> None: ...
    def confirmations(self, doc_id: str) -> list[Confirmation]: ...
    def append_confirmation(self, doc_id: str, c: Confirmation) -> None: ...
    def revision_dir(self, doc_id: str, model_revision: int) -> Path: ...
    def publish_revision(self, doc_id: str, model_revision: int, staging: Path) -> Path: ...
    def archive(self, doc_id: str, reason: str) -> Path | None: ...
    def lock(self, doc_id: str) -> threading.RLock: ...


class StaleRevision(Exception):
    def __init__(self, expected: int, actual: int):
        super().__init__(f"review revision {expected} is stale; current revision is {actual}")
        self.expected, self.actual = expected, actual


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class FileReviewStore:
    """<document dir>/review/{review.json, corrections.json, confirmations.json, revisions/<n>/}."""

    def __init__(self, doc_dir_of):
        self._doc_dir_of = doc_dir_of  # callable: doc_id -> Path (validated by the document store)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _dir(self, doc_id: str) -> Path:
        return self._doc_dir_of(doc_id) / "review"

    def lock(self, doc_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(doc_id, threading.RLock())  # re-entrant: service methods nest

    def load(self, doc_id: str) -> ReviewRecord | None:
        p = self._dir(doc_id) / "review.json"
        return ReviewRecord.model_validate_json(p.read_text(encoding="utf-8")) if p.is_file() else None

    def save(self, doc_id: str, record: ReviewRecord, expected_revision: int | None) -> None:
        """Atomic write; refuses if the stored revision is not the one the caller started from."""
        current = self.load(doc_id)
        if expected_revision is not None and current is not None and current.review_revision != expected_revision:
            raise StaleRevision(expected_revision, current.review_revision)
        _atomic_write(self._dir(doc_id) / "review.json", record.model_dump_json(indent=2))

    def _read_list(self, doc_id: str, name: str, cls):
        p = self._dir(doc_id) / name
        return [cls.model_validate(x) for x in json.loads(p.read_text(encoding="utf-8"))] if p.is_file() else []

    def _append(self, doc_id: str, name: str, items: list, item) -> None:
        _atomic_write(self._dir(doc_id) / name, json.dumps([i.model_dump(mode="json") for i in [*items, item]], indent=2, ensure_ascii=False))  # fmt: skip

    def corrections(self, doc_id: str) -> list[Correction]:
        return self._read_list(doc_id, "corrections.json", Correction)

    def append_correction(self, doc_id: str, c: Correction) -> None:
        self._append(doc_id, "corrections.json", self.corrections(doc_id), c)

    def confirmations(self, doc_id: str) -> list[Confirmation]:
        return self._read_list(doc_id, "confirmations.json", Confirmation)

    def append_confirmation(self, doc_id: str, c: Confirmation) -> None:
        self._append(doc_id, "confirmations.json", self.confirmations(doc_id), c)

    def revision_dir(self, doc_id: str, model_revision: int) -> Path:
        return self._dir(doc_id) / "revisions" / str(model_revision)

    def staging_dir(self, doc_id: str) -> Path:
        d = self._dir(doc_id) / "staging"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        return d

    def publish_revision(self, doc_id: str, model_revision: int, staging: Path) -> Path:
        """Revisions are write-once: an existing revision directory is never replaced."""
        target = self.revision_dir(doc_id, model_revision)
        if target.exists():
            raise FileExistsError(f"model revision {model_revision} already exists and is immutable")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)
        return target

    def archive(self, doc_id: str, reason: str) -> Path | None:
        d = self._dir(doc_id)
        if not d.exists():
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = self._doc_dir_of(doc_id) / "review_archive" / f"{stamp}"
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(d, target)
        (target / "ARCHIVED.txt").write_text(reason + "\n", encoding="utf-8")
        return target
