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


TOP_LEVEL_PATTERNS = [
    re.compile(r"\bpublic\s+(?:abstract\s+|sealed\s+|partial\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"\binternal\s+(?:abstract\s+|sealed\s+|partial\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"\bpublic\s+(?:partial\s+)?interface\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"\binternal\s+(?:partial\s+)?interface\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"\bpublic\s+(?:partial\s+)?record\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"\binternal\s+(?:partial\s+)?record\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"\bpublic\s+enum\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"\binternal\s+enum\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
]

METHOD_PATTERN = re.compile(
    r"""
    ^\s*
    (?:public|private|protected|internal|protected\s+internal|private\s+protected)
    (?:\s+static|\s+virtual|\s+override|\s+abstract|\s+async|\s+sealed|\s+extern|\s+new)*
    \s+
    [A-Za-z_<>\[\],\.\?\s]+
    \s+
    ([A-Za-z_][A-Za-z0-9_]*)
    \s*\(
    """,
    re.MULTILINE | re.VERBOSE,
)


def chunk_csharp_document(doc: SourceDocument) -> list[Chunk]:
    if doc.language != "csharp":
        return []

    path = doc.relative_path
    text = doc.text
    matches = _find_matches(text)

    if not matches:
        return [
            Chunk(
                id=f"{path}::full",
                path=path,
                language="csharp",
                chunk_type="full",
                symbol=_file_symbol(path),
                text=text,
            )
        ]

    chunks: list[Chunk] = []

    for index, (start, end, symbol, chunk_type) in enumerate(matches):
        chunk_text = text[start:end].strip()
        if not chunk_text:
            continue

        chunks.append(
            Chunk(
                id=f"{path}::{chunk_type}::{symbol}::{index}",
                path=path,
                language="csharp",
                chunk_type=chunk_type,
                symbol=symbol,
                text=chunk_text,
            )
        )

        if chunk_type in {"class", "interface", "record"}:
            chunks.extend(_extract_method_chunks(path, symbol, chunk_text, index))

    return chunks


def chunk_csharp_documents(documents: Iterable[SourceDocument]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in documents:
        chunks.extend(chunk_csharp_document(doc))
    return chunks


def _find_matches(text: str) -> list[tuple[int, int, str, str]]:
    found: list[tuple[int, str, str]] = []

    for pattern in TOP_LEVEL_PATTERNS:
        for match in pattern.finditer(text):
            symbol = match.group(1)
            chunk_type = _chunk_type_from_match(match.group(0))
            found.append((match.start(), symbol, chunk_type))

    found.sort(key=lambda item: item[0])

    deduped: list[tuple[int, str, str]] = []
    seen_starts: set[int] = set()

    for start, symbol, chunk_type in found:
        if start in seen_starts:
            continue
        seen_starts.add(start)
        deduped.append((start, symbol, chunk_type))

    results: list[tuple[int, int, str, str]] = []

    for i, (start, symbol, chunk_type) in enumerate(deduped):
        end = deduped[i + 1][0] if i + 1 < len(deduped) else len(text)
        results.append((start, end, symbol, chunk_type))

    return results


def _extract_method_chunks(path: str, parent_symbol: str, parent_text: str, parent_index: int) -> list[Chunk]:
    method_matches = list(METHOD_PATTERN.finditer(parent_text))
    if not method_matches:
        return []

    chunks: list[Chunk] = []

    for i, match in enumerate(method_matches):
        start = match.start()
        end = method_matches[i + 1].start() if i + 1 < len(method_matches) else len(parent_text)
        method_name = match.group(1)
        method_text = parent_text[start:end].strip()

        if not method_text:
            continue

        chunks.append(
            Chunk(
                id=f"{path}::method::{parent_symbol}.{method_name}::{parent_index}_{i}",
                path=path,
                language="csharp",
                chunk_type="method",
                symbol=f"{parent_symbol}.{method_name}",
                text=method_text,
            )
        )

    return chunks


def _chunk_type_from_match(match_text: str) -> str:
    if " class " in f" {match_text} ":
        return "class"
    if " interface " in f" {match_text} ":
        return "interface"
    if " record " in f" {match_text} ":
        return "record"
    if " enum " in f" {match_text} ":
        return "enum"
    return "type"


def _file_symbol(relative_path: str) -> str:
    name = relative_path.replace("\\", "/").split("/")[-1]
    return name.rsplit(".", 1)[0]
