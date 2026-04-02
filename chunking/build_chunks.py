from __future__ import annotations

from pathlib import Path
import re

from content_loader import load_documents
from vue_chunker import chunk_vue_documents
from ts_chunker import chunk_ts_documents
from csharp_chunker import chunk_csharp_documents


DEFAULT_EXPORT_MODE = "bundle"  # "bundle" (few files) or "per_file"
# Export bundle part size target (keep scanner max file size separate).
BUNDLE_PART_TARGET_BYTES = 250 * 1024


class _AdHocChunk:
    def __init__(
        self,
        path: str,
        language: str,
        chunk_type: str,
        symbol: str,
        start_line: int,
        end_line: int,
        text: str,
    ) -> None:
        self.path = path
        self.language = language
        self.chunk_type = chunk_type
        self.symbol = symbol
        self.start_line = start_line
        self.end_line = end_line
        self.text = text


def _safe_filename(relative_path: str) -> str:
    name = relative_path.replace("\\", "/")
    name = name.replace("/", "__")
    name = name.replace("..", ".")
    out = []
    for ch in name:
        if ch.isalnum() or ch in {"_", "-", ".", " "}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip().replace(" ", "_") + ".md"


def _fence_language(language: str) -> str:
    return {
        "typescript": "ts",
        "javascript": "js",
        "csharp": "csharp",
        "vue": "vue",
        "markdown": "md",
    }.get(language, "")


def _chunk_heading(chunk_type: str, symbol: str) -> str:
    if chunk_type == "full":
        return "## file"
    if symbol:
        return f"## {chunk_type}:{symbol}"
    return f"## {chunk_type}"


_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


def _iter_keyword_tokens(text: str) -> list[str]:
    if not text:
        return []
    tokens: list[str] = []
    for part in _NON_ALNUM_RE.split(text):
        if not part:
            continue
        for m in _CAMEL_RE.finditer(part):
            tok = m.group(0).strip().lower()
            if tok:
                tokens.append(tok)
    return tokens


def _keywords_for_chunk(doc, chunk) -> str:
    seen: set[str] = set()
    out: list[str] = []

    def add_many(items: list[str]) -> None:
        for item in items:
            if not item:
                continue
            if item in seen:
                continue
            seen.add(item)
            out.append(item)

    symbol = getattr(chunk, "symbol", "") or ""
    chunk_type = getattr(chunk, "chunk_type", "") or ""

    # symbol name split by casing
    add_many(_iter_keyword_tokens(symbol))

    # parent symbol if method
    if chunk_type == "method" and "." in symbol:
        parent = symbol.rsplit(".", 1)[0]
        add_many(_iter_keyword_tokens(parent))

    # relative path segments
    rel = (getattr(doc, "relative_path", "") or "").replace("\\", "/")
    for seg in [s for s in rel.split("/") if s and s != "."]:
        add_many(_iter_keyword_tokens(seg))
        if "." in seg:
            add_many(_iter_keyword_tokens(seg.rsplit(".", 1)[0]))

    # tags/category
    add_many(_iter_keyword_tokens(getattr(doc, "category", "") or ""))
    for t in getattr(doc, "tags", []) or []:
        add_many(_iter_keyword_tokens(str(t)))

    return ", ".join(out)


def _render_doc_markdown(doc, chunks: list[object]) -> str:
    fence = _fence_language(doc.language)

    lines: list[str] = []
    lines.append(f"# {doc.relative_path}")
    lines.append("")
    lines.append("- language: " + doc.language)
    lines.append("- category: " + doc.category)
    lines.append("- tags: " + ", ".join(doc.tags))
    if doc.sha256:
        lines.append("- sha256: " + doc.sha256)
    if doc.modified_utc:
        lines.append("- modified_utc: " + doc.modified_utc)
    lines.append("")

    for chunk in chunks:
        heading = _chunk_heading(getattr(chunk, "chunk_type", ""), getattr(chunk, "symbol", ""))
        lines.append(heading)
        lines.append("")
        # Deterministic, structural-only metadata per chunk.
        layer = _bundle_key(doc) or "other"
        start_line = getattr(chunk, "start_line", 1)
        end_line = getattr(chunk, "end_line", start_line)
        chunk_type = getattr(chunk, "chunk_type", "") or ""
        symbol = getattr(chunk, "symbol", "") or ""

        lines.append(f"- layer: {layer}")
        lines.append(f"- language: {doc.language}")
        lines.append(f"- category: {doc.category}")
        lines.append("- tags: " + ", ".join(doc.tags))
        lines.append(f"- chunk_type: {chunk_type}")
        if symbol:
            lines.append(f"- symbol: {symbol}")
        lines.append(f"- source: {doc.relative_path} (lines {start_line}-{end_line})")
        keywords = _keywords_for_chunk(doc, chunk)
        if keywords:
            lines.append(f"- keywords: {keywords}")
        lines.append("")
        lines.append(f"```{fence}".rstrip())
        lines.append(getattr(chunk, "text", "").rstrip())
        lines.append("```")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _write_markdown_doc(output_dir: Path, doc, chunks: list[object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / _safe_filename(doc.relative_path)
    out_path.write_text(_render_doc_markdown(doc, chunks), encoding="utf-8")


def _bundle_key(doc) -> str | None:
    lang = doc.language
    if lang in {"typescript", "javascript", "vue"}:
        return "frontend"
    if lang == "csharp":
        return "backend"
    if lang == "markdown":
        return "docs"
    return None


def _write_bundles(output_dir: Path, docs: list[object], chunks_by_path: dict[str, list[object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    def write_part(key: str, part_index: int, content: str) -> None:
        part_path = output_dir / f"{key}_part_{part_index:03d}.md"
        part_path.write_text(content.rstrip() + "\n", encoding="utf-8")

    docs_by_key: dict[str, list[object]] = {"frontend": [], "backend": [], "docs": []}
    for doc in sorted(docs, key=lambda d: d.relative_path.lower()):
        key = _bundle_key(doc)
        if key in docs_by_key:
            docs_by_key[key].append(doc)

    for key, key_docs in docs_by_key.items():
        part_index = 1
        buf: list[str] = []
        buf_bytes = 0

        for doc in key_docs:
            doc_chunks = chunks_by_path.get(doc.relative_path)
            if not doc_chunks:
                continue

            section = _render_doc_markdown(doc, doc_chunks)
            section_bytes = len(section.encode("utf-8"))

            if section_bytes > BUNDLE_PART_TARGET_BYTES:
                if buf:
                    write_part(key, part_index, "\n".join(buf))
                    part_index += 1
                    buf = []
                    buf_bytes = 0

                write_part(key, part_index, section)
                print(
                    f"WARNING: {doc.relative_path} section is ~{section_bytes} bytes; "
                    f"exceeds target {BUNDLE_PART_TARGET_BYTES} bytes; wrote as its own part."
                )
                part_index += 1
                continue

            if buf and (buf_bytes + section_bytes) > BUNDLE_PART_TARGET_BYTES:
                write_part(key, part_index, "\n".join(buf))
                part_index += 1
                buf = []
                buf_bytes = 0

            buf.append(section)
            buf_bytes += section_bytes

        if buf:
            write_part(key, part_index, "\n".join(buf))


def _print_openwebui_settings_hint() -> None:
    print("")
    print("Open WebUI settings (recommended):")
    print("- Admin Panel -> Settings -> Documents -> enable Markdown Header Splitting")
    print("- Tune Chunk Size / Overlap / Chunk Min Size Target based on your model context window")
    print(f"- Export part target size: ~{BUNDLE_PART_TARGET_BYTES} bytes per file")
    print("")


def _write_repo_index(output_dir: Path, docs: list[object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "repo_index.md"

    paths = sorted({d.relative_path for d in docs})
    by_dir: dict[str, list[str]] = {}
    for p in paths:
        directory = p.rsplit("/", 1)[0] if "/" in p else "."
        by_dir.setdefault(directory, []).append(p)

    lines: list[str] = []
    lines.append("# repo_index")
    lines.append("")
    lines.append(f"- file_count: {len(paths)}")
    lines.append("")
    lines.append("## files")
    lines.append("")

    for directory in sorted(by_dir):
        lines.append(f"### {directory}")
        lines.append("")
        for p in by_dir[directory]:
            lines.append(f"- {p}")
        lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_symbol_index(output_dir: Path, docs: list[object], chunks_by_path: dict[str, list[object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "symbol_index.md"

    doc_by_path: dict[str, object] = {d.relative_path: d for d in docs}

    rows: list[tuple[str, str, str, str, int, int, str, str]] = []
    for path in sorted(chunks_by_path.keys(), key=lambda p: p.lower()):
        doc = doc_by_path.get(path)
        if not doc:
            continue
        language = getattr(doc, "language", "") or ""
        category = getattr(doc, "category", "") or ""
        tags = ", ".join(getattr(doc, "tags", []) or [])
        for chunk in chunks_by_path.get(path, []):
            symbol = getattr(chunk, "symbol", "") or ""
            chunk_type = getattr(chunk, "chunk_type", "") or ""
            start_line = int(getattr(chunk, "start_line", 1) or 1)
            end_line = int(getattr(chunk, "end_line", start_line) or start_line)
            rows.append((symbol, chunk_type, language, path, start_line, end_line, category, tags))

    # Stable, deterministic sort for symbol lookup.
    rows.sort(key=lambda r: (r[0].lower(), r[3].lower(), r[4], r[1].lower()))

    lines: list[str] = []
    lines.append("# symbol_index")
    lines.append("")
    lines.append(f"- chunk_count: {len(rows)}")
    lines.append("")
    lines.append("## chunks")
    lines.append("")

    for symbol, chunk_type, language, path, start_line, end_line, category, tags in rows:
        lines.append(f"- symbol: {symbol}")
        lines.append(f"  - chunk_type: {chunk_type}")
        lines.append(f"  - language: {language}")
        lines.append(f"  - file: {path}")
        lines.append(f"  - lines: {start_line}-{end_line}")
        if category:
            lines.append(f"  - category: {category}")
        if tags:
            lines.append(f"  - tags: {tags}")
        lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    manifest_path = Path("kb_exports/scan_manifest.json")
    output_dir = Path("kb_exports/openwebui")

    docs = load_documents(manifest_path)

    vue_chunks = chunk_vue_documents(docs)
    ts_chunks = chunk_ts_documents(docs)
    csharp_chunks = chunk_csharp_documents(docs)

    chunks_by_path: dict[str, list[object]] = {}
    for chunk in [*vue_chunks, *ts_chunks, *csharp_chunks]:
        chunks_by_path.setdefault(chunk.path, []).append(chunk)

    for doc in docs:
        if doc.language == "markdown" and doc.relative_path not in chunks_by_path:
            end_line = doc.text.count("\n") + 1 if doc.text else 1
            chunks_by_path[doc.relative_path] = [
                _AdHocChunk(
                    path=doc.relative_path,
                    language="markdown",
                    chunk_type="full",
                    symbol=doc.relative_path.rsplit("/", 1)[-1],
                    start_line=1,
                    end_line=end_line,
                    text=doc.text,
                )
            ]

    if DEFAULT_EXPORT_MODE == "per_file":
        for doc in docs:
            doc_chunks = chunks_by_path.get(doc.relative_path)
            if not doc_chunks:
                continue
            _write_markdown_doc(output_dir, doc, doc_chunks)
    else:
        _write_bundles(output_dir, docs, chunks_by_path)

    _write_repo_index(output_dir, docs)
    _write_symbol_index(output_dir, docs, chunks_by_path)

    print(f"Loaded {len(docs)} documents")
    print(f"Wrote markdown exports to: {output_dir.resolve()}")
    if DEFAULT_EXPORT_MODE == "bundle":
        print("Bundled exports: frontend_part_###.md, backend_part_###.md, docs_part_###.md (only if content exists)")
    _print_openwebui_settings_hint()


if __name__ == "__main__":
    main()
