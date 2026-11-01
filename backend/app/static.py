"""Optional production-mode static serving of the built React frontend.

Active only when ``SERVE_FRONTEND=1`` AND ``frontend/dist`` exists — the
Vite dev workflow (npm run dev + /api proxy) is unaffected either way.

Behavior:
- ``/``                    → dist/index.html
- ``/assets/<file>``       → the real file, or 404 for unknown assets
- unknown **asset-looking** paths (contain a ``.`` or live under
  ``assets/``) → 404 with a JSON body (never silently return HTML)
- any other unknown path   → index.html (React client-side routing)
- ``/api/...``             → always handled by the API router (mounted first)
"""

from __future__ import annotations

import mimetypes

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse

_INDEX = "index.html"


def mount_spa(app: FastAPI, dist_path, *, mount_at: str = "/") -> None:
    """Mount the SPA at *mount_at* unless disabled or dist is missing.

    ``dist_path`` is ``Path``-like; imported loosely so unit tests can pass
    any readable path.
    """

    @app.get(mount_at + "{full_path:path}", include_in_schema=False)
    async def spa_proxy(request: Request, full_path: str) -> Response:
        dist = dist_path  # closure over settings-provided path

        if not dist.is_dir():
            return JSONResponse(
                status_code=404,
                content={"detail": "frontend build not found — run `npm run build` in frontend/"},
            )

        # Resolve the requested file inside dist/ (bounds-safe join).
        candidate = dist / full_path if full_path else dist / _INDEX
        resolved = candidate.resolve()
        if full_path and not resolved.is_relative_to(dist.resolve()):
            return JSONResponse(
                status_code=404,
                content={"detail": f"asset not found: {full_path}"},
            )
        if full_path and resolved.is_file():
            media_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            return FileResponse(resolved, media_type=media_type)

        # Asset-looking paths must never fall back to index.html.
        if _looks_like_asset(full_path):
            return JSONResponse(status_code=404, content={"detail": f"asset not found: {full_path}"})

        return FileResponse(dist / _INDEX, media_type="text/html")


def _looks_like_asset(full_path: str) -> bool:
    """Paths that carry a file extension or live under assets/ are assets."""
    trimmed = full_path.strip("/")
    if not trimmed:
        return False
    if trimmed.startswith("assets/"):
        return True
    last_segment = trimmed.rsplit("/", 1)[-1]
    return "." in last_segment