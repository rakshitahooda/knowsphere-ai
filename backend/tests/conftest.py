"""Shared test fixtures.

All tests run against the real `Settings` class but with overrides so they
never touch committed runtime data and never need network access.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture()
def test_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings instance pointed at a per-test temporary data directory.

    EMBEDDING_PROVIDER is forced to "fake" so the ENTIRE suite (M1→M3) runs
    offline: no torch, no model downloads, no sentence-transformers install
    required. Real-model behavior is covered by the opt-in M2 smoke test.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    return Settings()


@pytest.fixture()
def client(test_settings: Settings):
    """FastAPI TestClient with lifespan (storage dirs) executed."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(test_settings)) as test_client:
        yield test_client
