"""Deterministic Markdown section chunking."""

import re

from robot_rag.util import normalize_text, RagError, tokenize


_HEADING = re.compile(r'^(#{1,6})\s+(.+?)\s*$')
_SENTENCE_BOUNDARY = re.compile(r'(?<=[。！？!?])|(?<=[.])\s+')


def _sections(markdown):
    title = 'Untitled'
    heading = None
    lines = []
    sections = []
    for raw_line in markdown.splitlines():
        match = _HEADING.match(raw_line)
        if not match:
            lines.append(raw_line)
            continue
        level = len(match.group(1))
        text = match.group(2).strip()
        if level == 1 and heading is None:
            title = text
            lines = []
            continue
        if heading is not None:
            body = '\n'.join(lines).strip()
            if body:
                sections.append((heading, body))
        heading = text
        lines = []
    if heading is not None:
        body = '\n'.join(lines).strip()
        if body:
            sections.append((heading, body))
    if not sections:
        body = '\n'.join(lines).strip()
        if body:
            sections.append((title, body))
    return title, sections


def _sentence_windows(body, max_terms, overlap_terms):
    sentences = [
        sentence.strip()
        for sentence in _SENTENCE_BOUNDARY.split(body)
        if sentence.strip()
    ]
    windows = []
    current = []
    current_terms = 0
    for sentence in sentences:
        count = len(tokenize(sentence))
        if count > max_terms:
            raise RagError(
                'one curated sentence exceeds max_terms; split the source '
                'instead of silently truncating it'
            )
        if current and current_terms + count > max_terms:
            windows.append(' '.join(current))
            overlap = []
            overlap_count = 0
            for previous in reversed(current):
                previous_count = len(tokenize(previous))
                if overlap_count + previous_count > overlap_terms:
                    break
                overlap.insert(0, previous)
                overlap_count += previous_count
            current = overlap
            current_terms = overlap_count
        current.append(sentence)
        current_terms += count
    if current:
        windows.append(' '.join(current))
    return windows


def chunk_markdown(markdown, max_terms, overlap_terms):
    """Split Markdown by headings and bounded overlapping sentence windows."""
    if overlap_terms >= max_terms:
        raise RagError('overlap_terms must be smaller than max_terms')
    title, sections = _sections(markdown)
    chunks = []
    for heading, body in sections:
        for window in _sentence_windows(body, max_terms, overlap_terms):
            text = normalize_text(f'{title}\n{heading}\n{window}')
            chunks.append({'heading': heading, 'text': text})
    if not chunks:
        raise RagError('source produced no non-empty chunks')
    return chunks
