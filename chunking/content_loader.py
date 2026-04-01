from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SourceDocument:
    path: str
    relative_path: str
    language: str
    category: str
    tags: list[str]
    sha256: str
    modified_utc: str
    text: str


def load_manifest(manifest_path: str | Path) -> list[dict]:
    manifest_file = Path(manifest_path)
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    return payload.get("files", [])


def read_text_file(path: str | Path) -> str | None:
    file_path = Path(path)

    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            text = file_path.read_text(encoding=encoding)
            return normalize_text(text)
        except UnicodeDecodeError:
            continue
        except OSError:
            return None

    return None


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def load_documents(manifest_path: str | Path) -> list[SourceDocument]:
    records = load_manifest(manifest_path)
    documents: list[SourceDocument] = []

    for record in records:
        text = read_text_file(record["path"])
        if not text:
            continue

        documents.append(
            SourceDocument(
                path=record["path"],
                relative_path=record["relative_path"],
                language=record["language"],
                category=record["category"],
                tags=record["tags"],
                sha256=record.get("sha256", ""),
                modified_utc=record.get("modified_utc", ""),
                text=text,
            )
        )

    return documents


if __name__ == "__main__":
    docs = load_documents("kb_exports/scan_manifest.json")
    print(f"Loaded {len(docs)} documents")
    if docs:
        print(docs[0].relative_path)
        print(docs[0].language)
        print(docs[0].text[:500])
