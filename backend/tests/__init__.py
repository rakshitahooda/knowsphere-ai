"""KnowSphere AI backend test suite.

Runs offline: no network access, no Ollama/ChromaDB/sentence-transformers
downloads. Tests exercise what exists (config, app factory, health API) and
fake providers will be introduced in M2 to keep that guarantee.
"""
