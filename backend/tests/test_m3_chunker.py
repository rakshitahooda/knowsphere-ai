"""M3 tests: chunking — overlap, size bounds, page preservation, merging."""

from __future__ import annotations

import pytest

from app.ingestion.chunker import ChunkerConfig, chunk_sections, _word_windows
from app.ingestion.parse import TextSection

# --------------------------------------------------------------------- #
# helpers                                                                #
# --------------------------------------------------------------------- #


def words(count: int) -> list[str]:
    return [f"w{i:03d}" for i in range(count)]


def section(text: str, page: int | None = 1, section_number: int = 1) -> TextSection:
    return TextSection(text=text, page=page, section=section_number)


# --------------------------------------------------------------------- #
# window engine                                                          #
# --------------------------------------------------------------------- #


def test_windows_overlap_by_trailing_words() -> None:
    cfg = ChunkerConfig(max_chars=66, overlap_chars=28, min_chars=5)
    windows = _word_windows(words(30), cfg)

    assert len(windows) == 4  # 13-word windows stepping 7 words
    # overlap words of window 1 == trailing words of window 0
    assert windows[1][:6] == windows[0][-6:]
    assert windows[2][:6] == windows[1][-6:]


def test_overlap_configured_behavior_generalizes() -> None:
    cfg = ChunkerConfig(max_chars=100, overlap_chars=50, min_chars=10)
    ws = _word_windows(words(60), cfg)

    assert len(ws) >= 2
    # The next window must START with the trailing words of the previous one.
    overlap_len = max(
        k for k in range(1, min(len(ws[0]), len(ws[1])) + 1)
        if ws[1][:k] == ws[0][-k:]
    )
    assert overlap_len >= 5  # proportional to overlap_chars configuration


def test_single_token_longer_than_max_is_its_own_window() -> None:
    long_word = "x" * 500
    cfg = ChunkerConfig(max_chars=100, overlap_chars=30, min_chars=5)  # token far exceeds max
    windows = _word_windows([long_word] + words(5), cfg)

    assert windows[0] == [long_word]  # progress guaranteed, no crash
    assert windows[1] == words(5)


def test_empty_input_yields_no_windows() -> None:
    assert _word_windows([], ChunkerConfig()) == []


# --------------------------------------------------------------------- #
# config validation                                                      #
# --------------------------------------------------------------------- #


def test_overlap_must_be_smaller_than_max() -> None:
    with pytest.raises(ValueError):
        ChunkerConfig(max_chars=100, overlap_chars=100)


@pytest.mark.parametrize("bad", [0, -5])
def test_max_chars_must_be_positive(bad: int) -> None:
    with pytest.raises(ValueError):
        ChunkerConfig(max_chars=bad, overlap_chars=10)


def test_negative_overlap_rejected() -> None:
    with pytest.raises(ValueError):
        ChunkerConfig(max_chars=100, overlap_chars=-1)


# --------------------------------------------------------------------- #
# section → chunk level                                                  #
# --------------------------------------------------------------------- #


def test_chunks_respect_max_chars_across_all_sections() -> None:
    cfg = ChunkerConfig(max_chars=60, overlap_chars=12, min_chars=10)
    sections = [
        section(" ".join(words(50)), page=1),
        section(" ".join(words(50)), page=2),
    ]

    chunks = chunk_sections(sections, cfg)

    assert all(len(c.text) <= 60 for c in chunks)  # word-packing bound
    assert {c.page for c in chunks} == {1, 2}


def test_page_metadata_preserved_per_section() -> None:
    """Per-page tokens make page attribution unambiguous."""
    tokens_page7 = " ".join(f"p7w{i:02d}" for i in range(30))
    tokens_page8 = " ".join(f"p8w{i:02d}" for i in range(30))
    cfg = ChunkerConfig(max_chars=50, overlap_chars=10, min_chars=5)
    sections = [section(tokens_page7, page=7, section_number=1), section(tokens_page8, page=8, section_number=2)]

    chunks = chunk_sections(sections, cfg)

    for chunk in chunks:
        expected = 7 if chunk.section == 1 else 8
        assert chunk.page == expected


def test_page_none_propagates_for_plaintext() -> None:
    chunks = chunk_sections([section(" ".join(words(10)), page=None)], ChunkerConfig())
    assert chunks and all(c.page is None for c in chunks)


def test_small_tail_is_merged_into_previous_chunk() -> None:
    cfg = ChunkerConfig(max_chars=66, overlap_chars=28, min_chars=40)
    # words(28): last window has only 6 words (~29 chars) < min_chars → merge
    windows = _word_windows(words(28), cfg)
    texts = [" ".join(w) for w in windows]
    assert len(texts[-1]) < 40  # genuinely a small tail

    chunked = chunk_sections([section(" ".join(words(28)))], cfg)
    merged_texts = [c.text for c in chunked]

    assert len(merged_texts) == len(texts) - 1  # tail merged
    assert merged_texts[-1].endswith(texts[-1])


def test_global_chunk_index_is_sequential() -> None:
    chunks = chunk_sections(
        [section(" ".join(words(40)), page=1), section(" ".join(words(40)), page=2)],
        ChunkerConfig(max_chars=50, overlap_chars=10, min_chars=5),
    )
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_empty_section_list_yields_no_chunks() -> None:
    assert chunk_sections([], ChunkerConfig()) == []


def test_whitespace_only_section_skipped() -> None:
    chunks = chunk_sections(
        [section("   \n  "), section("real text here", page=2)],
        ChunkerConfig(),
    )
    assert len(chunks) == 1
    assert chunks[0].page == 2
