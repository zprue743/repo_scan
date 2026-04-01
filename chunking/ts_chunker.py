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


EXPORT_PATTERNS = [
    re.compile(
        r"export\s+(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        re.MULTILINE,
    ),
    re.compile(
        r"export\s+class\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        re.MULTILINE,
    ),
    re.compile(
        r"export\s+interface\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        re.MULTILINE,
    ),
    re.compile(
        r"export\s+type\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        re.MULTILINE,
    ),
    re.compile(
        r"export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
        re.MULTILINE,
    ),
]


def chunk_ts_document(doc: SourceDocument) -> list[Chunk]:
    if doc.language not in {"typescript", "javascript"}:
        return []

    path = doc.relative_path
    text = doc.text
    matches = _find_matches(text)

    if not matches:
        return [
            Chunk(
                id=f"{path}::full",
                path=path,
                language=doc.language,
                chunk_type="full",
                symbol=_file_symbol(path),
                start_line=1,
                end_line=_line_number_at(text, len(text)),
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
                language=doc.language,
                chunk_type=chunk_type,
                symbol=symbol,
                start_line=_line_number_at(text, start),
                end_line=_line_number_at(text, end),
                text=chunk_text,
            )
        )

    return chunks


def chunk_ts_documents(documents: Iterable[SourceDocument]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in documents:
        chunks.extend(chunk_ts_document(doc))
    return chunks


def _find_matches(text: str) -> list[tuple[int, int, str, str]]:
    found: list[tuple[int, str, str]] = []

    for pattern in EXPORT_PATTERNS:
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
        improved_end = _improve_end(text, start, end, chunk_type)
        results.append((start, improved_end, symbol, chunk_type))

    return results


def _chunk_type_from_match(match_text: str) -> str:
    if "function" in match_text:
        return "function"
    if "class" in match_text:
        return "class"
    if "interface" in match_text:
        return "interface"
    if "type" in match_text:
        return "type"
    if "const" in match_text:
        return "const"
    return "export"


def _file_symbol(relative_path: str) -> str:
    name = relative_path.replace("\\", "/").split("/")[-1]
    return name.rsplit(".", 1)[0]


def _line_number_at(text: str, index: int) -> int:
    if index <= 0:
        return 1
    if index >= len(text):
        return text.count("\n") + 1
    return text.count("\n", 0, index) + 1


def _improve_end(text: str, start: int, next_start: int, chunk_type: str) -> int:
    if chunk_type not in {"function", "class"}:
        return next_start

    brace_open = text.find("{", start, next_start)
    if brace_open == -1:
        return next_start

    depth = 0
    for i in range(brace_open, min(len(text), next_start)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1

    return next_start
