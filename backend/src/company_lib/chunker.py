"""Markdown-aware overlapping chunker."""
from __future__ import annotations

import re


def chunk_markdown(text: str, *, size: int = 1600, overlap: int = 240) -> list[str]:
    text = text.strip()
    if not text:
        return []
    sections = re.split(r"(?=^#{1,4}\s)", text, flags=re.MULTILINE)
    chunks: list[str] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= size:
            chunks.append(section)
            continue
        start = 0
        while start < len(section):
            end = min(start + size, len(section))
            if end < len(section):
                boundary = section.rfind("\n", start + size // 2, end)
                if boundary > start:
                    end = boundary
            chunks.append(section[start:end].strip())
            if end >= len(section):
                break
            start = max(end - overlap, start + 1)
    return chunks
