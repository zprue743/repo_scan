from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from content_loader import load_documents
from vue_chunker import chunk_vue_documents
from ts_chunker import chunk_ts_documents
from csharp_chunker import chunk_csharp_documents


def write_jsonl(path: Path, chunks: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")


def main() -> None:
    manifest_path = Path("kb_exports/scan_manifest.json")
    output_dir = Path("kb_exports")

    docs = load_documents(manifest_path)

    vue_chunks = chunk_vue_documents(docs)
    ts_chunks = chunk_ts_documents(docs)
    csharp_chunks = chunk_csharp_documents(docs)

    all_chunks = [
        *vue_chunks,
        *ts_chunks,
        *csharp_chunks,
    ]

    write_jsonl(output_dir / "vue_chunks.jsonl", vue_chunks)
    write_jsonl(output_dir / "ts_chunks.jsonl", ts_chunks)
    write_jsonl(output_dir / "csharp_chunks.jsonl", csharp_chunks)
    write_jsonl(output_dir / "all_chunks.jsonl", all_chunks)

    print(f"Loaded {len(docs)} documents")
    print(f"Wrote {len(vue_chunks)} vue chunks")
    print(f"Wrote {len(ts_chunks)} ts/js chunks")
    print(f"Wrote {len(csharp_chunks)} csharp chunks")
    print(f"Wrote {len(all_chunks)} total chunks")


if __name__ == "__main__":
    main()
