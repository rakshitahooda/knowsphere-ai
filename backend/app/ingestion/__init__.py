"""KnowSphere AI — document ingestion subpackage (M3).

- parse.py      files → TextSection(provenance) structures
- chunker.py    sections → overlapped, page-preserving chunks
- pipeline.py   orchestration: validate → dedupe → store file → parse →
                chunk → embed → index → write metadata; cleanup on failure
"""
