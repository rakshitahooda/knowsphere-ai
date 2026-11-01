"""Application configuration.

Everything runtime-tunable lives here and is sourced from the project-root
`.env` file (see `.env.example`). Relative paths (e.g. DATA_DIR=data) are
resolved against the project root, not the current working directory, so the
backend behaves identically when started from `backend/` or the repo root.

Secrets (e.g. OPENROUTER_API_KEY) are read from the environment only — they
are never written to files or logs by this module.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# knowsphere-ai/backend/app/config.py → parents[2] is the project root.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

LLMProviderName = Literal["ollama", "openrouter", "fake"]

EmbeddingProviderName = Literal["sentence-transformers", "fake"]


class Settings(BaseSettings):
    """Central configuration, loaded once and injected via app.state."""

    # --- identity ---------------------------------------------------
    app_name: str = "KnowSphere AI"
    version: str = "0.1.0"

    # --- provider-agnostic LLM configuration -------------------------
    llm_provider: LLMProviderName = "ollama"

    # Ollama — local inference, no API key required (DEFAULT).
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.1:8b"

    # OpenRouter — optional cloud access, including eligible free models.
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""  # intentionally empty; set in .env only
    openrouter_chat_model: str = "meta-llama/llama-3.3-70b-instruct:free"

    # --- embeddings (local, CPU by default) --------------------------
    # embedding_provider: "sentence-transformers" (default) or "fake"
    # ("fake" exists for tests/offline demos; the real adapter is local-only).
    embedding_provider: EmbeddingProviderName = "sentence-transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"

    # --- storage ------------------------------------------------------
    data_dir: Path = Path("data")  # relative → resolved against PROJECT_ROOT

    # --- ingestion (M3) -----------------------------------------------
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB, matches .env.example
    chunk_max_chars: int = 1000
    chunk_overlap_chars: int = 200

    # --- retrieval / chat (M4) -----------------------------------------
    retrieval_top_k: int = 5            # chunks fetched per question
    min_similarity: float = 0.30        # cosine-similarity floor (0..1)
    chat_history_messages: int = 8      # recent messages included in prompts

    # --- CORS ----------------------------------------------------------
    cors_origins: str = "http://localhost:5173"

    # --- frontend static serving (M6, optional) -------------------------
    # SERVE_FRONTEND=1 → FastAPI also serves the built React app from
    # frontend/dist (production mode). Never needed for `npm run dev`.
    serve_frontend: bool = False
    frontend_dist_dir: Path = Path("frontend/dist")  # relative to PROJECT_ROOT

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Derived values (computed, not stored, so overrides in tests are    #
    # always honored without re-instantiation tricks)                    #
    # ------------------------------------------------------------------ #

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def _resolve(self, relative: Path) -> Path:
        """Resolve *relative* paths against the project root."""
        return relative if relative.is_absolute() else PROJECT_ROOT / relative

    @property
    def data_path(self) -> Path:
        return self._resolve(self.data_dir)

    @property
    def uploads_path(self) -> Path:
        return self.data_path / "uploads"

    @property
    def chroma_path(self) -> Path:
        """ChromaDB persistent storage location."""
        return self.data_path / "chroma"

    @property
    def database_path(self) -> Path:
        """SQLite database file (metadata + conversation history)."""
        return self.data_path / "knowsphere.db"

    @property
    def frontend_dist_path(self) -> Path:
        """Built React app location (resolved from the project root)."""
        return self._resolve(self.frontend_dist_dir)

    def ensure_storage_dirs(self) -> None:
        """Create the runtime directory layout on boot (idempotent)."""
        for path in (self.data_path, self.uploads_path, self.chroma_path):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings accessor (used by tooling and scripts)."""
    return Settings()
