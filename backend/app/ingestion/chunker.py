"""Text chunking with overlap — configurable, word-boundary safe.

Chunks are built *within* a section: a PDF page never bleeds into the next
page's chunk. That keeps every chunk's ``page`` metadata exact (which the
frontend citation cards in M5 will rely on), at the cost of small chunks at
page boundaries — a good trade for RAG.

Sizing is in characters but packing respects word boundaries, so chunks
never cut words in half (except single "words" longer than max_chars —
typically URLs — which become their own oversized chunk; that guarantees
forward progress and keeps the pipeline simple).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.ingestion.parse import IngestionError, TextSection

@dataclass(frozen=True, slots=True)
class ChunkerConfig:
    """All sizes in characters (approximate — chunk text is word-joined)."""

    max_chars: int = 1000
    overlap_chars: int = 200
    #: Tails smaller than this are merged into the previous chunk.
    min_chars: int = 80

    def __post_init__(self) -> None:
        if self.max_chars < 1:
            raise ValueError("max_chars must be positive")
        if self.overlap_chars < 0:
            raise ValueError("overlap_chars must be >= 0")
        if self.overlap_chars >= self.max_chars:
            raise ValueError("overlap_chars must be smaller than max_chars")


@dataclass(frozen=True, slots=True)
class Chunk:
    text: str
    page: int | None
    section: int
    index: int  # global 0-based chunk ordinal across the whole document


class ChunkingError(IngestionError):
    pass


def chunk_sections(
    sections: Sequence[TextSection],
    config: ChunkerConfig,
) -> list[Chunk]:
    """Chunk every section, preserving page/section metadata per chunk."""
    if not sections:
        return []
    chunks: list[Chunk] = []
    index = 0
    for section in sections:
        windows = _word_windows(section.text.split(), config)
        texts = [" ".join(window) for window in windows]
        # Merge a too-small tail into its predecessor (same section, because
        # sections are as large as one chunk).
        if len(texts) > 1 and len(texts[-1]) < config.min_chars:
            texts[-2] = f"{texts[-2]} {texts[-1]}"
            texts.pop()
        for text in texts:
            chunks.append(Chunk(text=text, page=section.page, section=section.section, index=index))
            index += 1
    return chunks


def _word_windows(words: Sequence[str], config: ChunkerConfig) -> list[list[str]]:
    """Slide a word window across *words* with the configured overlap.

    Returns a list of word lists. Always yields at least one list; the
    absolute position advances by ``taken - overlap_words >= 1`` on every
    step, so the algorithm terminates.
    """
    out: list[list[str]] = []
    position = 0
    total = len(words)

    while position < total:
        taken: list[str] = []
        size = 0
        cursor = position
        while cursor < total:
            word = words[cursor]
            addition = len(word) + (1 if taken else 0)
            if size + addition <= config.max_chars:
                taken.append(word)
                size += addition
                cursor += 1
            else:
                break
        if not taken:
            # Single token longer than max_chars: its own window (documented
            # exception above). Keeps the loop progressing.
            taken = [words[position]]
            cursor = position + 1

        out.append(taken)
        taken_count = cursor - position
        if cursor >= total:
            break

        # Overlap: carry the trailing words of this window into the next one,
        # walking back from the window's end until >= overlap_chars is accrued.
        back = 0
        accumulated = 0
        while back < taken_count - 1 and accumulated < config.overlap_chars:
            last = taken[-1 - back]
            accumulated += len(last) + (1 if back else 0)
            back += 1
        position += taken_count - back

    return out
