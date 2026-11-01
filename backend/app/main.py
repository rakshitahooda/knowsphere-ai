"""FastAPI application factory.

Boot flow (lifespan): create the runtime directory layout (data/, uploads/,
chroma/), then serve. Settings are instantiated once and attached to
`app.state.settings` so routers and future pipelines read a single source of
truth — and tests can inject their own instance.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import Settings, get_settings

DESCRIPTION = """
Chat with your own documents, locally. Ingestion, embedding, retrieval and
inference are provider-agnostic: the default workflow runs key-free with
Ollama + sentence-transformers on CPU; OpenRouter (including eligible free
models) is available via configuration only.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    settings.ensure_storage_dirs()
    # M3: build the ingestion stack once (embedder is lazy — no model load
    # or download happens at startup; it loads on first upload).
    from app.core.embeddings import build_embedder
    from app.core.retrieval.retriever import Retriever, RetrieverConfig
    from app.core.retrieval.vector_store import ChromaVectorStore
    from app.core.rag_pipeline import RAGPipeline
    from app.core.llm import ProviderError, build_provider
    from app.db.conversations import ConversationRepository
    from app.db.repository import DocumentRepository
    from app.ingestion.chunker import ChunkerConfig
    from app.ingestion.pipeline import DocumentIngestor

    embedder = build_embedder(settings)
    vector_store = ChromaVectorStore(settings.chroma_path)
    documents_repository = DocumentRepository(settings.database_path)

    app.state.ingestor = DocumentIngestor(
        repository=documents_repository,
        vector_store=vector_store,
        embedder=embedder,
        uploads_dir=settings.uploads_path,
        max_upload_bytes=settings.max_upload_bytes,
        chunker_config=ChunkerConfig(
            max_chars=settings.chunk_max_chars,
            overlap_chars=settings.chunk_overlap_chars,
        ),
    )

    # M4: the chat pipeline reuses the SAME store/embedder/documents repo.
    retriever = Retriever(
        store=vector_store,
        embedder=embedder,
        config=RetrieverConfig(
            top_k=settings.retrieval_top_k,
            min_similarity=settings.min_similarity,
        ),
    )
    # Provider errors (e.g. openrouter selected but key missing) must NOT
    # crash the whole app: capture and surface them per-request as an
    # in-stream `provider_not_configured` error event.
    try:
        provider = build_provider(settings)
        provider_config_error: str | None = None
    except ProviderError as exc:
        provider = None
        provider_config_error = str(exc)

    app.state.rag_pipeline = RAGPipeline(
        retriever=retriever,
        provider=provider,
        conversations=ConversationRepository(settings.database_path),
        documents=documents_repository,
        top_k=settings.retrieval_top_k,
        history_limit=settings.chat_history_messages,
        provider_config_error=provider_config_error,
    )
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the KnowSphere AI API application."""
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    # M6, optional: serve the built React app (production mode). The /api
    # router above always wins; SPA fallback handles client-side routing.
    if settings.serve_frontend:
        from app.static import mount_spa

        mount_spa(app, settings.frontend_dist_path)
    return app


# Module-level instance for `uvicorn app.main:app`.
app = create_app()
