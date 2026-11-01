"""M6 tests: optional production-mode SPA serving (SERVE_FRONTEND)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

# --------------------------------------------------------------------- #
# helpers                                                                #
# --------------------------------------------------------------------- #


def build_dist(tmp_path, *, index_html: str | None = None, assets: bool = True):
    """Create <tmp>/dist layout as produced by `npm run build`."""
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text(
        index_html
        or "<!doctype html><html><head><title>KnowSphere AI</title></head><body><div id=root></div></body></html>",
        encoding="utf-8",
    )
    if assets:
        (dist / "assets").mkdir()
        (dist / "assets" / "index-abc123.js").write_text("console.log('app')", encoding="utf-8")
        (dist / "assets" / "index-def456.css").write_text("body{}", encoding="utf-8")
    return dist


def make_spa_client(tmp_path, monkeypatch: pytest.MonkeyPatch, *, serve: bool):
    """Context manager yielding a client whose lifespan has run."""
    import contextlib

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    dist = build_dist(tmp_path)
    settings = Settings(serve_frontend=serve, frontend_dist_dir=dist)

    @contextlib.contextmanager
    def _client():
        with TestClient(create_app(settings)) as client:
            yield client

    return _client


@pytest.fixture()
def spa_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    with make_spa_client(tmp_path, monkeypatch, serve=True)() as client:
        yield client


@pytest.fixture()
def api_only_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    with make_spa_client(tmp_path, monkeypatch, serve=False)() as client:
        yield client


# --------------------------------------------------------------------- #
# SPA behavior                                                           #
# --------------------------------------------------------------------- #


def test_root_serves_index_html(spa_client: TestClient) -> None:
    response = spa_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "KnowSphere AI" in response.text


def test_known_assets_are_served_with_correct_types(spa_client: TestClient) -> None:
    js = spa_client.get("/assets/index-abc123.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    css = spa_client.get("/assets/index-def456.css")
    assert css.status_code == 200
    assert "css" in css.headers["content-type"]


def test_unknown_asset_paths_return_404_not_html(spa_client: TestClient) -> None:
    response = spa_client.get("/assets/nonexistent-hash.js")
    assert response.status_code == 404


def test_client_side_routes_fall_back_to_index_html(spa_client: TestClient) -> None:
    """Future React routing (e.g. /conversations/xyz) must serve the app shell."""
    response = spa_client.get("/conversations/some-id")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "KnowSphere AI" in response.text


def test_api_routes_not_shadowed_by_spa(spa_client: TestClient) -> None:
    health = spa_client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    # docs endpoints remain intact as well
    assert spa_client.get("/api/documents").status_code == 200
    assert spa_client.get("/docs").status_code == 200  # OpenAPI UI still reachable


def test_traversal_attempt_is_rejected(spa_client: TestClient) -> None:
    response = spa_client.get("/../../backend/app/config.py")
    assert response.status_code == 404


# --------------------------------------------------------------------- #
# disabled / missing dist                                                #
# --------------------------------------------------------------------- #


def test_serve_frontend_false_leaves_no_catchall(api_only_client: TestClient) -> None:
    """Vite dev workflow: no static mount, unknown paths behave as before."""
    assert api_only_client.get("/").status_code == 404
    assert api_only_client.get("/api/health").status_code == 200


def test_serve_frontend_without_dist_returns_helpful_404(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    settings = Settings(serve_frontend=True, frontend_dist_dir=tmp_path / "no-build-here")

    with TestClient(create_app(settings)) as client:
        response = client.get("/")

    assert response.status_code == 404
    assert "npm run build" in response.json()["detail"]
