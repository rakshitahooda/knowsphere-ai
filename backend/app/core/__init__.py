"""Core domain logic.

- llm/         M2: LLMProvider protocol + Ollama / OpenRouter adapters
- embeddings/  M2/M3: Embedder protocol + sentence-transformers adapter
- retrieval/   M3: chunker, ChromaDB vector store, retriever
- rag_pipeline.py  M4: end-to-end query pipeline (retrieve → prompt → stream)

Deliberately empty in Phase M1: interfaces land in M2 so that nothing else
couples to a concrete SDK.
"""
