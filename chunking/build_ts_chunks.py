from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from content_loader import load_documents
from ts_chunker import chunk_ts_documents


def main() -> None:
    docs = load_documents("kb_exports/scan_manifest.json")
    chunks = chunk_ts_documents(docs)

    output_path = Path("kb_exports/ts_chunks.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")

    print(f"Wrote {len(chunks)} ts/js chunks to {output_path}")


if __name__ == "__main__":
    main()
