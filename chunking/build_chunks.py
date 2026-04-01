from __future__ import annotations

from pathlib import Path

from content_loader import load_documents
from vue_chunker import chunk_vue_documents
from ts_chunker import chunk_ts_documents
from csharp_chunker import chunk_csharp_documents


DEFAULT_EXPORT_MODE = "bundle"  # "bundle" (few files) or "per_file"


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
        start_line = getattr(chunk, "start_line", 1)
        end_line = getattr(chunk, "end_line", start_line)
        lines.append(f"source: {doc.relative_path} (lines {start_line}-{end_line})")
        if getattr(chunk, "symbol", ""):
            lines.append(f"symbol: {chunk.symbol}")
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

    bundle_paths = {
        "frontend": output_dir / "frontend.md",
        "backend": output_dir / "backend.md",
        "docs": output_dir / "docs.md",
    }

    parts: dict[str, list[str]] = {"frontend": [], "backend": [], "docs": []}

    for doc in docs:
        key = _bundle_key(doc)
        if not key:
            continue
        doc_chunks = chunks_by_path.get(doc.relative_path)
        if not doc_chunks:
            continue
        parts[key].append(_render_doc_markdown(doc, doc_chunks))

    for key, content_parts in parts.items():
        if not content_parts:
            continue
        bundle_paths[key].write_text("\n".join(content_parts).rstrip() + "\n", encoding="utf-8")


def _print_openwebui_settings_hint() -> None:
    print("")
    print("Open WebUI settings (recommended):")
    print("- Admin Panel -> Settings -> Documents -> enable Markdown Header Splitting")
    print("- Tune Chunk Size / Overlap / Chunk Min Size Target based on your model context window")
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

    if DEFAULT_EXPORT_MODE == "per_file":
        for doc in docs:
            doc_chunks = chunks_by_path.get(doc.relative_path)
            if not doc_chunks:
                continue
            _write_markdown_doc(output_dir, doc, doc_chunks)
    else:
        _write_bundles(output_dir, docs, chunks_by_path)

    _write_repo_index(output_dir, docs)

    print(f"Loaded {len(docs)} documents")
    print(f"Wrote markdown exports to: {output_dir.resolve()}")
    if DEFAULT_EXPORT_MODE == "bundle":
        print("Bundled exports: frontend.md, backend.md, docs.md (only if content exists)")
    _print_openwebui_settings_hint()


if __name__ == "__main__":
    main()
