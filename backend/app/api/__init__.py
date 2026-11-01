"""API layer.

Routers are mounted under the `/api` prefix so the Vite dev server can proxy
them to the backend with a single, stable rule.

- M1: health
- M3: /documents (upload, list, delete)
- M4: /chat (streaming RAG endpoint)
"""

from fastapi import APIRouter

from app.api import health, routes_chat, routes_docs

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(routes_docs.router)
api_router.include_router(routes_chat.router)
