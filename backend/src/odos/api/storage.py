"""File-based document store. Paths are derived only from validated UUIDs."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from odos.api.schemas import ArtifactInfo, DeletionItem, DeletionPreview, DocumentStatus, JobStatus
from odos.artifact_names import ARTIFACTS, DOCLING_MARKDOWN, DOCLING_RAW, EXTRACTION_META


class NotFound(Exception):
    pass


class DeleteBlocked(Exception):
    """The document exists but must not be deleted now (running job, unexpected symbolic link)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


DERIVED_FIELDS = {"artifacts", "document_type", "review_state"}  # filled on read, never written to meta.json


def safe_display_name(name: str | None) -> str:
    base = (name or "document.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[^\w.\- ()äöüÄÖÜß]", "_", base).strip(" .") or "document.pdf"
    return base[:120]


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def doc_dir(self, doc_id: str) -> Path:
        try:
            canonical = str(uuid.UUID(doc_id))
        except (ValueError, AttributeError, TypeError):
            raise NotFound(doc_id) from None
        if canonical != doc_id:  # lowercase canonical form only (case-insensitive filesystems)
            raise NotFound(doc_id)
        d = (self.root / canonical).resolve()
        if d.parent != self.root:  # defence in depth against traversal
            raise NotFound(doc_id)
        return d

    def create(self, filename: str, size: int) -> tuple[str, Path]:
        doc_id = str(uuid.uuid4())
        d = self.doc_dir(doc_id)
        d.mkdir(parents=True)
        st = DocumentStatus(id=doc_id, filename=safe_display_name(filename), size_bytes=size,
                            uploaded_at=datetime.now(timezone.utc), status=JobStatus.UPLOADED)  # fmt: skip
        self.write(st)
        return doc_id, d / "original.pdf"

    def _meta(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "meta.json"

    def write(self, st: DocumentStatus) -> None:
        with self._lock:
            tmp = self._meta(st.id).with_suffix(".tmp")
            tmp.write_text(st.model_dump_json(exclude=DERIVED_FIELDS, indent=2), encoding="utf-8")
            tmp.replace(self._meta(st.id))

    def read(self, doc_id: str) -> DocumentStatus:
        p = self._meta(doc_id)
        if not p.is_file():
            raise NotFound(doc_id)
        st = DocumentStatus.model_validate(json.loads(p.read_text(encoding="utf-8")))
        st.artifacts = self.artifacts(doc_id)
        st.document_type = self._json_field(self.classification_path(doc_id), "document_type")
        st.review_state = self._json_field(self.doc_dir(doc_id) / "review" / "review.json", "state")
        return st

    @staticmethod
    def _json_field(path: Path, key: str) -> str | None:
        """One string field of a small JSON file next to the document; None if absent or unreadable."""
        try:
            v = json.loads(path.read_text(encoding="utf-8")).get(key)
        except (OSError, ValueError, AttributeError):
            return None
        return v if isinstance(v, str) else None

    def update(self, doc_id: str, **changes) -> DocumentStatus:
        with self._lock:
            p = self._meta(doc_id)
            st = DocumentStatus.model_validate(json.loads(p.read_text(encoding="utf-8")))
            for k, v in changes.items():
                setattr(st, k, v)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(st.model_dump_json(exclude=DERIVED_FIELDS, indent=2), encoding="utf-8")
            tmp.replace(p)
        return self.read(doc_id)

    def list(self) -> list[DocumentStatus]:
        out = []
        for d in self.root.iterdir():
            try:
                out.append(self.read(d.name))
            except (NotFound, ValueError, OSError):
                continue
        return sorted(out, key=lambda s: s.uploaded_at, reverse=True)

    def original(self, doc_id: str) -> Path:
        p = self.doc_dir(doc_id) / "original.pdf"
        if not p.is_file():
            raise NotFound(doc_id)
        return p

    def output_dir(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "artifacts"

    def artifact_path(self, doc_id: str, type_: str) -> Path:
        if type_ not in ARTIFACTS:  # whitelist: the URL never selects a file name
            raise NotFound(type_)
        p = self.output_dir(doc_id) / ARTIFACTS[type_][0]
        if not p.is_file():
            raise NotFound(type_)
        return p

    def artifacts(self, doc_id: str) -> list[ArtifactInfo]:
        out = []
        for t, (fname, media) in ARTIFACTS.items():
            p = self.output_dir(doc_id) / fname
            if p.is_file():
                out.append(ArtifactInfo(type=t, filename=fname, media_type=media, size_bytes=p.stat().st_size, url=f"/api/documents/{doc_id}/artifacts/{t}"))  # fmt: skip
        return out

    KEEP_ON_REPROCESS = (DOCLING_RAW, DOCLING_MARKDOWN, EXTRACTION_META)  # one Docling run per PDF
    EXPORT_DIRS = ("akn4eu",)

    def clear_outputs(self, doc_id: str) -> None:
        d = self.output_dir(doc_id)
        if d.is_dir():
            for f in d.iterdir():
                if f.is_file() and f.name not in self.KEEP_ON_REPROCESS:
                    f.unlink()
                elif f.is_dir() and f.name in self.EXPORT_DIRS:  # exports belong to the previous model
                    shutil.rmtree(f)

    def classification_path(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "classification.json"  # outside artifacts/: survives reprocessing

    def read_classification(self, doc_id: str):
        from odos.classification import ClassificationResult

        p = self.classification_path(doc_id)
        if not p.is_file():
            return None
        try:
            return ClassificationResult.model_validate_json(p.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def write_classification(self, doc_id: str, result) -> None:
        p = self.classification_path(doc_id)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(p)

    # ---- deletion ----------------------------------------------------------------------------------------------
    @staticmethod
    def _tree(path: Path) -> tuple[int, int, list[Path]]:
        """(files, bytes, symbolic links) below path, never following links."""
        files = size = 0
        links: list[Path] = []
        if path.is_symlink():
            return 0, 0, [path]
        if path.is_file():
            return 1, path.stat().st_size, []
        for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
            for n in [*dirnames, *filenames]:
                q = Path(dirpath) / n
                if q.is_symlink():
                    links.append(q)
                elif n in filenames:
                    files += 1
                    size += q.stat().st_size
        return files, size, links

    def _preview(self, d: Path, st: DocumentStatus) -> DeletionPreview:
        """Everything inside the document's own directory, grouped; the directory is validated by the caller."""
        names = {
            "original.pdf": ("original_pdf", "Uploaded PDF"),
            "meta.json": ("metadata", "Document record (status and processing summary)"),
            "classification.json": ("classification", "Document classification"),
            "artifacts": ("generated_artifacts", "Generated artifacts (extraction, structure, Akoma Ntoso and AKN4EU exports, reports)"),
            "review": ("review", "Human review (corrections, confirmations, approval and all review revisions)"),
            "review_archive": ("review_archive", "Archived reviews of earlier processing runs"),
        }
        items: dict[str, DeletionItem] = {}
        links: list[Path] = []
        for child in sorted(d.iterdir(), key=lambda p: p.name):
            cat, label = names.get(child.name, ("other", "Other files in this document's folder"))
            n, b, ln = self._tree(child)
            links += ln
            it = items.setdefault(cat, DeletionItem(category=cat, label=label, files=0, size_bytes=0))
            it.files += n
            it.size_bytes += b
            if cat == "generated_artifacts":
                it.details = sorted({p.name for p in child.rglob("*") if p.is_file() and not p.is_symlink()})
            elif cat == "review":
                revs = child / "revisions"
                count = sum(1 for x in revs.iterdir() if x.is_dir()) if revs.is_dir() else 0
                corr = self._json_len(child / "corrections.json")
                it.details = [f"{count} review revision(s)", f"{corr} correction(s)"]
            elif cat == "review_archive":
                it.details = [f"{sum(1 for x in child.iterdir() if x.is_dir())} archived review(s)"]
        reason = None
        if st.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
            reason = "This document is queued or being processed. Wait until processing has finished."
        elif links:
            reason = f"The document folder contains {len(links)} symbolic link(s); ODOS never follows them and will not delete such a folder."
        order = ["original_pdf", "generated_artifacts", "classification", "review", "review_archive", "other", "metadata"]
        out = [items[c] for c in order if c in items]
        return DeletionPreview(id=st.id, filename=st.filename, can_delete=reason is None, blocked_reason=reason, items=out,
                               total_files=sum(i.files for i in out), total_bytes=sum(i.size_bytes for i in out))  # fmt: skip

    @staticmethod
    def _json_len(path: Path) -> int:
        try:
            v = json.loads(path.read_text(encoding="utf-8"))
            return len(v) if isinstance(v, list) else 0
        except (OSError, ValueError):
            return 0

    def _own_dir(self, doc_id: str) -> Path:
        """The document directory, only if it is a real directory directly below the store root."""
        d = self.doc_dir(doc_id)  # UUID-validated and resolved
        if (self.root / doc_id).is_symlink() or not d.is_dir() or not (d / "meta.json").is_file():
            raise NotFound(doc_id)
        return d

    def deletion_preview(self, doc_id: str) -> DeletionPreview:
        d = self._own_dir(doc_id)
        return self._preview(d, self.read(doc_id))

    def delete(self, doc_id: str) -> DeletionPreview:
        """Permanently remove one document's directory. Returns what was removed.

        The path is derived only from the validated UUID. Children are removed first and meta.json last, so a
        failure part-way leaves a document that is still listed and can be deleted again."""
        with self._lock:
            d = self._own_dir(doc_id)
            st = DocumentStatus.model_validate(json.loads((d / "meta.json").read_text(encoding="utf-8")))
            preview = self._preview(d, st)
            if not preview.can_delete:
                raise DeleteBlocked("document_busy" if st.status in (JobStatus.QUEUED, JobStatus.PROCESSING) else "unsafe_document_folder", preview.blocked_reason or "")  # fmt: skip
            for child in sorted(d.iterdir(), key=lambda p: (p.name == "meta.json", p.name)):
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            d.rmdir()
            return preview
