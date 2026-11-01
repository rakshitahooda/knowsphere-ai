# Release preparation — v1.0.0

Everything in this file is prepared but **not yet executed**: the first commit,
tag `v1.0.0`, GitHub repo publication and the GitHub Release itself still need
explicit approval & manual action. Suggested order: commit first, publish the
repo, then create the tag & release.

---

## 1. Repository description (GitHub "About")

> Local-first RAG chat over your own documents: FastAPI + React, SQLite +
> ChromaDB, Ollama inference, streamed answers with real citations.

(Fits GitHub's ~350-char About limit; the app runs fully local and key-free.)

## 2. Suggested GitHub topics

```
rag
retrieval-augmented-generation
local-llm
ollama
chromadb
sqlite
fastapi
react
typescript
vite
sentence-transformers
document-chat
citations
local-first
llm
```

(GitHub caps topics at 20 per repo, lowercase, no spaces.)

## 3. Concise release summary

KnowSphere AI is a local-first RAG application: upload PDF/TXT/MD/DOCX files,
and chat about them with an LLM that grounds every answer in retrieved
passages and shows the source it used. The default stack is 100% local and
key-free — sentence-transformers embeddings on CPU, Ollama for inference, one
SQLite file for metadata/history, and ChromaDB for vectors. An optional
OpenRouter adapter unlocks cloud models without code changes. Conversation
history (rename/delete with confirmation) persists locally, and FastAPI can
optionally serve the built React frontend on a single port. Windows 11 is the
first-class documented platform.

## 4. Release notes — `v1.0.0`

```markdown
# KnowSphere AI v1.0.0

Local-first retrieval-augmented chat over your own documents.
Everything runs on your machine by default — no accounts, no API keys.

## Highlights

- **Grounded streaming chat** — questions retrieve the top-k most similar
  chunks (configurable k + similarity floor) and the answer streams token by
  token over SSE, with a strict "say you don't know" rule instead of guessing.
- **Real citations** — every answer carries source cards (document name, page,
  chunk reference, expandable snippet); citations are never fabricated.
- **Document ingestion** — drag & drop or browse upload for PDF · TXT · MD ·
  DOCX (≤ 20 MB each) with per-file progress, validation errors and duplicate
  detection; word-boundary chunking with overlap; PDF page numbers preserved.
- **Conversations** — rename inline, delete with confirmation; full history
  persisted in SQLite and included in later prompts.
- **Provider-agnostic LLM layer** — Ollama (default, local, key-free) and
  OpenRouter (optional cloud / free-tier models); embeddings behind a separate
  interface. Plain httpx, no SDK wrappers.
- **Prompt-injection defense** — retrieved document text is treated as
  untrusted data inside <context> delimiters and never followed as
  instructions.
- **Production mode** — FastAPI can serve the built React frontend directly
  (SERVE_FRONTEND=1): one process, one port, proper 404s for stale assets.

## Stack

Python 3.10+ · FastAPI · SQLite · ChromaDB · sentence-transformers
(all-MiniLM-L6-v2, CPU) · Ollama (default) · React 19 + TypeScript (strict) +
Vite 6 · Vitest + pytest.

## Verification (performed locally, Windows 11)

- Backend: pytest — 146 passed, 1 skipped (opt-in real-embedder smoke test)
- Frontend: vitest — 66 passed
- Type safety + build: `tsc --noEmit` clean; `vite build` succeeds
- Live smoke runs: dev mode (Vite proxy) and production mode (FastAPI serving
  `frontend/dist`) both verified end-to-end with a real Ollama model

## Honest limitations

- Local 8B-class models can still phrase or summarize imperfectly.
- No OCR for scanned/image-only PDFs; embedding model is English-centric.
- Single-user, no auth — intended for personal/local use only, not a
  multi-tenant service (not audited or load-tested).
- Docker presets were evaluated and deliberately skipped (native Windows setup
  is the documented path); see README for the rationale.

## Getting started

See the README "Installation & setup (Windows 11)" section — a venv, an
Ollama model pull and `npm install` are all you need.
```

## 5. Recommended commit message (first commit / release commit)

Subject + body, ≤ 72-char lines:

```
feat: KnowSphere AI v1.0.0 — local-first RAG chat with citations

FastAPI backend (retrieval → grounded streaming → citations → SQLite
history) + React/TypeScript frontend (upload, streaming chat, source
cards, conversation rename/delete). Default pipeline: sentence-
transformers embeddings on CPU, ChromaDB vectors, Ollama inference
(key-free); optional OpenRouter adapter. Includes production-mode
frontend serving, prompt-injection defenses and offline test suites
(pytest 146 passed / 1 skipped, vitest 66 passed, tsc strict clean).

Phases M1–M7: scaffold, provider layer, ingestion, streaming RAG,
chat UI, hardening/docs, release preparation (screenshots, release
notes).
```

Short one-liner variant for the tag annotation:

```
KnowSphere AI v1.0.0 — local-first RAG chat with citations
```

## 6. Manual release checklist (for the user, in order)

1. [ ] Review staged work and create the first commit (message in §5).
2. [ ] Create the GitHub repository (Name: `knowsphere-ai`; description from
       §1; topics from §2; **Private** unless deliberately publishing).
3. [ ] Add the remote and push `main`:
       `git remote add origin <url> && git push -u origin main`.
4. [ ] Tag after everything is on GitHub:
       `git tag -a v1.0.0 -m "KnowSphere AI v1.0.0" && git push origin v1.0.0`.
5. [ ] Create the GitHub Release from tag `v1.0.0`, title
       **KnowSphere AI v1.0.0**, notes from §4 (check "Set as latest").
6. [ ] Verify no secrets after push (`git log -p | grep -i sk-or` style spot
       check) — expected: only offline-test dummy keys.
