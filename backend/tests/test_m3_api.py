"""M3 tests: /api/documents HTTP surface (upload, list, get, delete, errors).

Runs against the real app with the fake embedder and a real (tmp) Chroma +
SQLite, exercising multipart handling and the IngestionError→HTTP mapping.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    with TestClient(create_app(Settings())) as test_client:
        yield test_client


def upload(client: TestClient, name: str, body: bytes, content_type: str = "text/plain"):
    return client.post("/api/documents", files={"file": (name, body, content_type)})


LONG_BODY = (
    "The quick brown fox jumps over the lazy dog while the sun rises eastward " * 20
).encode()


# --------------------------------------------------------------------- #
# happy paths                                                            #
# --------------------------------------------------------------------- #


def test_upload_returns_201_with_metadata(client: TestClient) -> None:
    resp = upload(client, "notes.txt", LONG_BODY)

    assert resp.status_code == 201
    meta = resp.json()
    assert meta["status"] == "ready"
    assert meta["original_name"] == "notes.txt"
    assert meta["num_chunks"] >= 2
    assert meta["size_bytes"] == len(LONG_BODY)
    assert meta["created_at"]


def test_list_and_get_metadata(client: TestClient) -> None:
    created = upload(client, "doc.txt", LONG_BODY).json()

    listing = client.get("/api/documents")
    assert listing.status_code == 200
    assert [d["id"] for d in listing.json()] == [created["id"]]

    single = client.get(f"/api/documents/{created['id']}")
    assert single.status_code == 200
    assert single.json() == created


def test_delete_lifecycle(client: TestClient) -> None:
    created = upload(client, "gone.txt", LONG_BODY).json()

    deleted = client.delete(f"/api/documents/{created['id']}")
    assert deleted.status_code == 204

    assert client.get(f"/api/documents/{created['id']}").status_code == 404
    assert client.get("/api/documents").json() == []


# --------------------------------------------------------------------- #
# error mapping                                                          #
# --------------------------------------------------------------------- #


def test_duplicate_upload_maps_to_409(client: TestClient) -> None:
    upload(client, "original.txt", LONG_BODY)
    duplicate = upload(client, "renamed.txt", LONG_BODY)  # same bytes

    assert duplicate.status_code == 409
    assert "identical" in duplicate.json()["detail"]


def test_unsupported_type_maps_to_415(client: TestClient) -> None:
    assert upload(client, "binary.exe", b"MZ").status_code == 415


def test_empty_upload_maps_to_400(client: TestClient) -> None:
    assert upload(client, "void.txt", b"").status_code == 400


def test_corrupted_upload_maps_to_400(client: TestClient) -> None:
    assert upload(client, "broken.pdf", b"%PDF-1.4 not a real pdf").status_code == 400


def test_unknown_document_maps_to_404(client: TestClient) -> None:
    assert client.get("/api/documents/missing").status_code == 404
    assert client.delete("/api/documents/missing").status_code == 404


def test_oversized_upload_maps_to_413(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    settings = Settings(max_upload_bytes=50)

    with TestClient(create_app(settings)) as client:
        resp = upload(client, "overflow.txt", b"x" * 51)

    assert resp.status_code == 413
    assert "limit" in resp.json()["detail"]


def test_multipart_write_with_unicode_filename(client: TestClient) -> None:
    # Unicode display names are accepted: sanitization only governs the
    # STORED filename; original_name is preserved verbatim for the UI.
    resp = upload(client, "résumé vôtre.md", b"# heading")

    assert resp.status_code == 201
    body = resp.json()
    assert body["original_name"] == "résumé vôtre.md"
    assert "\\" not in body["stored_name"]
