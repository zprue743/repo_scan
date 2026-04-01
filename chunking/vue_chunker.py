from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from content_loader import SourceDocument


@dataclass(slots=True)
class Chunk:
    id: str
    path: str
    language: str
    chunk_type: str
    symbol: str
    start_line: int
    end_line: int
    text: str


TEMPLATE_RE = re.compile(r"<template\b[^>]*>(.*?)</template>", re.DOTALL | re.IGNORECASE)
SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)


def chunk_vue_document(doc: SourceDocument) -> list[Chunk]:
    if doc.language != "vue":
        return []

    symbol = _file_symbol(doc.relative_path)
    chunks: list[Chunk] = []

    template = _match_block(TEMPLATE_RE, doc.text)
    script = _match_block(SCRIPT_RE, doc.text)
    style = _match_block(STYLE_RE, doc.text)

    if template:
        template_text, template_start, template_end = template
        chunks.append(
            Chunk(
                id=f"{doc.relative_path}::template",
                path=doc.relative_path,
                language="vue",
                chunk_type="template",
                symbol=symbol,
                start_line=_line_number_at(doc.text, template_start),
                end_line=_line_number_at(doc.text, template_end),
                text=template_text,
            )
        )

    if script:
        script_text, script_start, script_end = script
        chunks.append(
            Chunk(
                id=f"{doc.relative_path}::script",
                path=doc.relative_path,
                language="vue",
                chunk_type="script",
                symbol=symbol,
                start_line=_line_number_at(doc.text, script_start),
                end_line=_line_number_at(doc.text, script_end),
                text=script_text,
            )
        )

    if style:
        style_text, style_start, style_end = style
        chunks.append(
            Chunk(
                id=f"{doc.relative_path}::style",
                path=doc.relative_path,
                language="vue",
                chunk_type="style",
                symbol=symbol,
                start_line=_line_number_at(doc.text, style_start),
                end_line=_line_number_at(doc.text, style_end),
                text=style_text,
            )
        )

    if not chunks:
        chunks.append(
            Chunk(
                id=f"{doc.relative_path}::full",
                path=doc.relative_path,
                language="vue",
                chunk_type="full",
                symbol=symbol,
                start_line=1,
                end_line=_line_number_at(doc.text, len(doc.text)),
                text=doc.text,
            )
        )

    return chunks


def chunk_vue_documents(documents: Iterable[SourceDocument]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in documents:
        chunks.extend(chunk_vue_document(doc))
    return chunks


def _match_block(pattern: re.Pattern[str], text: str) -> tuple[str, int, int] | None:
    match = pattern.search(text)
    if not match:
        return None

    content = match.group(1).strip()
    if not content:
        return None

    start = match.start(1)
    end = match.end(1)
    return (content, start, end)


def _file_symbol(relative_path: str) -> str:
    name = relative_path.replace("\\", "/").split("/")[-1]
    return name.rsplit(".", 1)[0]


def _line_number_at(text: str, index: int) -> int:
    if index <= 0:
        return 1
    if index >= len(text):
        return text.count("\n") + 1
    return text.count("\n", 0, index) + 1
