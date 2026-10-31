"""Document deletion API. Every test uses its own temporary storage; no real user document is ever touched."""

import json
import shutil
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from odos.api.app import create_app
from odos.api.config import Settings
from test_api import MINI_PDF, fake_pipeline, settings, upload, wait


@pytest.fixture()
def env(tmp_path):
    """Two documents plus sentinel files that must survive any deletion (shared schemas, source, other data)."""
    sentinels = {
        tmp_path / "schemas" / "akn-3.1-os" / "akomantoso30.xsd": "schema",
        tmp_path / "src" / "odos" / "app.py": "source",
        tmp_path / "storage" / "README.txt": "next to documents/, not inside a document",
        tmp_path / "keep.txt": "outside the store",
    }
    for p, t in sentinels.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t)
    with TestClient(create_app(settings(tmp_path), fake_pipeline())) as c:
        a, b = upload(c, "a.pdf").json()["id"], upload(c, "b.pdf").json()["id"]
        root = tmp_path / "storage" / "documents"
        yield c, a, b, root, sentinels


def seed(root: Path, doc_id: str) -> None:
    """A fully processed and reviewed document folder (artifacts, two review revisions, an archive)."""
    d = root / doc_id
    (d / "artifacts" / "akn4eu").mkdir(parents=True)
    (d / "artifacts" / "document_model.json").write_text("{}")
    (d / "artifacts" / "document_akn.xml").write_text("<x/>")
    (d / "artifacts" / "akn4eu" / "akn4eu_package.zip").write_bytes(b"PK")
    for r in (0, 1):
        (d / "review" / "revisions" / str(r)).mkdir(parents=True)
        (d / "review" / "revisions" / str(r) / "document_akn.xml").write_text("<x/>")
    (d / "review" / "review.json").write_text(json.dumps({"state": "in_review"}))
    (d / "review" / "corrections.json").write_text(json.dumps([{"id": "c1"}, {"id": "c2"}]))
    (d / "review_archive" / "20261029T000000Z").mkdir(parents=True)
    (d / "review_archive" / "20261029T000000Z" / "ARCHIVED.txt").write_text("x")


def snapshot(path: Path) -> dict[str, bytes]:
    return {str(p.relative_to(path)): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


# ---- preview ----------------------------------------------------------------------------------------------------
def test_preview_names_every_category_and_changes_nothing(env):
    c, a, b, root, _ = env
    seed(root, a)
    before = snapshot(root)
    r = c.get(f"/api/documents/{a}/deletion-preview")
    assert r.status_code == 200
    p = r.json()
    assert p["id"] == a and p["filename"] == "a.pdf" and p["can_delete"] is True and p["blocked_reason"] is None
    cats = {i["category"]: i for i in p["items"]}
    assert list(cats) == ["original_pdf", "generated_artifacts", "classification", "review", "review_archive", "metadata"]
    assert cats["original_pdf"]["files"] == 1 and cats["original_pdf"]["size_bytes"] == len(MINI_PDF)
    assert cats["generated_artifacts"]["details"] == ["akn4eu_package.zip", "document_akn.xml", "document_model.json"]
    assert cats["review"]["details"] == ["2 review revision(s)", "2 correction(s)"]
    assert cats["review_archive"]["details"] == ["1 archived review(s)"]
    assert p["total_files"] == sum(i["files"] for i in p["items"]) == len(snapshot(root / a))
    assert p["total_bytes"] == sum(len(v) for v in snapshot(root / a).values())
    assert snapshot(root) == before  # read-only


# ---- deletion ---------------------------------------------------------------------------------------------------
def test_delete_removes_only_the_selected_document(env):
    c, a, b, root, sentinels = env
    seed(root, a)
    seed(root, b)
    b_before = snapshot(root / b)
    r = c.delete(f"/api/documents/{a}")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] is True and body["id"] == a and body["filename"] == "a.pdf"
    assert body["removed"]["total_files"] == body["removed"]["total_files"] > 8 and body["removed"]["can_delete"]
    assert not (root / a).exists()  # really gone from disk
    assert snapshot(root / b) == b_before  # the other document is byte-identical
    assert all(p.read_text() == t for p, t in sentinels.items())  # schemas, source and other files untouched
    assert [d["id"] for d in c.get("/api/documents").json()] == [b]
    assert c.get(f"/api/documents/{a}/status").status_code == 404
    assert c.get(f"/api/documents/{a}/original").status_code == 404
    assert c.delete(f"/api/documents/{a}").status_code == 404  # already gone


def test_delete_leaves_no_trace_of_review_data(env):
    c, a, _, root, _ = env
    seed(root, a)
    assert c.delete(f"/api/documents/{a}").status_code == 200
    assert not list(root.glob(f"{a}*")) and not list(root.rglob("review*")) or all(a not in str(p) for p in root.rglob("*"))


@pytest.mark.parametrize("bad", ["..", "../..", "%2e%2e", "..%2F..%2Fkeep.txt", "not-a-uuid", "0" * 36, "../" + "0" * 36,
                                 "12345678-1234-1234-1234-123456789ABC", "documents", "a/b", "%00"])  # fmt: skip
def test_invalid_or_hostile_ids_delete_nothing(env, bad):
    c, a, b, root, sentinels = env
    before = snapshot(root.parent.parent)
    r = c.delete(f"/api/documents/{bad}")
    assert r.status_code in (404, 405)  # unknown id, or the path never reaches the delete route at all
    assert snapshot(root.parent.parent) == before  # nothing anywhere under the test directory changed
    assert (root / a).is_dir() and (root / b).is_dir()


def test_uppercase_uuid_is_not_an_alias_for_a_document(env):
    c, a, _, root, _ = env
    assert c.delete(f"/api/documents/{a.upper()}").status_code == 404
    assert (root / a).is_dir()


def test_symlinked_document_folder_is_never_followed(env, tmp_path):
    c, a, b, root, sentinels = env
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "meta.json").write_text("{}")
    (victim / "important.txt").write_text("do not delete")
    link = root / "11111111-1111-4111-8111-111111111111"
    link.symlink_to(victim, target_is_directory=True)
    assert c.delete("/api/documents/11111111-1111-4111-8111-111111111111").status_code == 404
    assert c.get("/api/documents/11111111-1111-4111-8111-111111111111/deletion-preview").status_code == 404
    assert (victim / "important.txt").read_text() == "do not delete" and (victim / "meta.json").exists()
    assert link.is_symlink()


def test_symlink_inside_a_document_blocks_deletion(env, tmp_path):
    c, a, _, root, _ = env
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (root / a / "artifacts").mkdir()
    (root / a / "artifacts" / "evil").symlink_to(outside, target_is_directory=True)
    p = c.get(f"/api/documents/{a}/deletion-preview").json()
    assert p["can_delete"] is False and "symbolic link" in p["blocked_reason"]
    r = c.delete(f"/api/documents/{a}")
    assert r.status_code == 409 and r.json()["code"] == "unsafe_document_folder"
    assert (outside / "keep.txt").read_text() == "keep" and (root / a / "original.pdf").exists()  # nothing removed


def test_running_job_blocks_deletion(tmp_path):
    gate = threading.Event()
    with TestClient(create_app(settings(tmp_path), fake_pipeline(gate))) as c:
        doc = upload(c).json()["id"]
        c.post(f"/api/documents/{doc}/process", json={"mode": "extract_only"})
        wait(c, doc, ("processing", "queued"))
        p = c.get(f"/api/documents/{doc}/deletion-preview").json()
        assert p["can_delete"] is False and "processing" in p["blocked_reason"].lower()
        r = c.delete(f"/api/documents/{doc}")
        assert r.status_code == 409 and r.json()["code"] == "document_busy"
        assert (tmp_path / "storage" / "documents" / doc / "original.pdf").exists()
        gate.set()
        wait(c, doc, ("completed", "failed"))
        assert c.delete(f"/api/documents/{doc}").status_code == 200  # fine once it has finished


def test_failed_deletion_keeps_the_document_listed_and_retryable(env, monkeypatch):
    c, a, _, root, _ = env
    seed(root, a)
    real = shutil.rmtree

    def boom(path, *args, **kw):
        if Path(path).name == "review":
            raise PermissionError(13, "Permission denied")
        return real(path, *args, **kw)

    monkeypatch.setattr(shutil, "rmtree", boom)
    r = c.delete(f"/api/documents/{a}")
    assert r.status_code == 500 and r.json()["code"] == "delete_failed" and "still listed" in r.json()["message"]
    assert (root / a / "meta.json").exists() and a in [d["id"] for d in c.get("/api/documents").json()]
    monkeypatch.setattr(shutil, "rmtree", real)
    assert c.delete(f"/api/documents/{a}").status_code == 200 and not (root / a).exists()


# ---- listing: derived, never persisted ------------------------------------------------------------------------
def test_listing_reports_type_and_review_state_without_persisting_them(env):
    c, a, b, root, _ = env
    seed(root, a)
    (root / b / "classification.json").write_text(json.dumps({"document_type": "eu_regulation"}))
    by_id = {d["id"]: d for d in c.get("/api/documents").json()}
    assert by_id[a]["review_state"] == "in_review" and by_id[b]["document_type"] == "eu_regulation"
    assert by_id[b]["review_state"] is None and by_id[a]["document_type"] is not None  # a was classified at upload
    c.post(f"/api/documents/{a}/process", json={"mode": "extract_only"})
    wait(c, a)
    meta = json.loads((root / a / "meta.json").read_text())  # rewritten by the job: derived fields stay out
    assert "document_type" not in meta and "review_state" not in meta and "artifacts" not in meta
    st = c.get(f"/api/documents/{a}/status").json()
    # the stub PDF is not a legal text; processing again archives the review (existing behaviour), so none is active
    assert st["document_type"] == "unknown" and st["review_state"] is None
    assert list((root / a / "review_archive").iterdir())


def test_cors_allows_delete_for_the_dev_frontend(tmp_path):
    s = Settings(storage_dir=tmp_path / "storage", cors_origins=("http://localhost:5173",))
    with TestClient(create_app(s, fake_pipeline())) as c:
        r = c.options("/api/documents/x", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "DELETE"})
        assert r.status_code == 200 and "DELETE" in r.headers["access-control-allow-methods"]
