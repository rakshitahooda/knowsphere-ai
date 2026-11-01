"""Phase M1 tests: configuration, app factory, and the health endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_health_reports_ok_and_active_config(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app_name"] == "KnowSphere AI"
    # Default, key-free provider configuration must be reported accurately.
    assert body["llm_provider"] == "ollama"
    assert body["embedding_model"] == "sentence-transformers/all-MiniLM-L6-v2"
    # Health must never leak secrets.
    assert "api_key" not in body
    assert "openrouter_api_key" not in body


def test_custom_settings_are_respected(tmp_path) -> None:
    """create_app() must honor an injected Settings instance (no globals)."""
    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        app_name="KnowSphere AI (test)",
        data_dir=tmp_path / "custom",
        cors_origins="http://test.local",
        ollama_base_url="http://localhost:9999",
    )
    app = create_app(settings)

    resp = TestClient(app).get("/api/health")
    assert resp.json()["app_name"] == "KnowSphere AI (test)"

    assert settings.cors_origin_list == ["http://test.local"]
    # Relative paths resolve against the project root; absolute ones stay as-is.
    assert settings.data_path.is_absolute()
    assert settings.data_path == (tmp_path / "custom").resolve()
    assert settings.chroma_path == settings.data_path / "chroma"
    assert settings.database_path.name == "knowsphere.db"
    assert settings.ollama_base_url == "http://localhost:9999"


def test_lifespan_creates_storage_layout(client: TestClient, test_settings) -> None:
    """Boot (lifespan) materializes data/, uploads/ and chroma/."""
    assert test_settings.data_path.is_dir()
    assert test_settings.uploads_path.is_dir()
    assert test_settings.chroma_path.is_dir()


def test_unknown_route_returns_404(client: TestClient) -> None:
    assert client.get("/api/does-not-exist").status_code == 404


def test_default_workflow_requires_no_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The local (Ollama) default must be selectable without any API key."""
    from app.config import Settings

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    settings = Settings(llm_provider="ollama")
    assert settings.openrouter_api_key == ""
    assert settings.ollama_base_url.startswith("http://localhost")
