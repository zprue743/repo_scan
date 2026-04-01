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
        chunks.append(
            Chunk(
                id=f"{doc.relative_path}::template",
                path=doc.relative_path,
                language="vue",
                chunk_type="template",
                symbol=symbol,
                text=template,
            )
        )

    if script:
        chunks.append(
            Chunk(
                id=f"{doc.relative_path}::script",
                path=doc.relative_path,
                language="vue",
                chunk_type="script",
                symbol=symbol,
                text=script,
            )
        )

    if style:
        chunks.append(
            Chunk(
                id=f"{doc.relative_path}::style",
                path=doc.relative_path,
                language="vue",
                chunk_type="style",
                symbol=symbol,
                text=style,
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
                text=doc.text,
            )
        )

    return chunks


def chunk_vue_documents(documents: Iterable[SourceDocument]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in documents:
        chunks.extend(chunk_vue_document(doc))
    return chunks


def _match_block(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None

    content = match.group(1).strip()
    return content or None


def _file_symbol(relative_path: str) -> str:
    name = relative_path.replace("\\", "/").split("/")[-1]
    return name.rsplit(".", 1)[0]
