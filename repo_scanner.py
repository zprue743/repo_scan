from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SUPPORTED_EXTENSIONS = {
    ".cs": "csharp",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "vue",
    ".js": "javascript",
    ".jsx": "javascript",
    ".md": "markdown",
}

DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".vs",
    ".vscode",
    "node_modules",
    "bin",
    "obj",
    "dist",
    "build",
    "coverage",
    ".nuxt",
    ".next",
    ".output",
    ".dart_tool",
    ".turbo",
    ".cache",
    "__pycache__",
}

DEFAULT_EXCLUDED_FILE_PATTERNS = {
    "*.min.js",
    "*.min.css",
    "*.bundle.js",
    "*.generated.cs",
    "*.g.cs",
    "*.g.i.cs",
    "*.designer.cs",
    "*.d.ts",
    "*.map",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
}

DEFAULT_INCLUDED_GLOBS = [
    "**/*.cs",
    "**/*.ts",
    "**/*.tsx",
    "**/*.vue",
    "**/*.js",
    "**/*.jsx",
    "**/*.md",
]


@dataclass(slots=True)
class FileRecord:
    path: str
    relative_path: str
    extension: str
    language: str
    size_bytes: int
    sha256: str
    modified_utc: str
    category: str
    tags: list[str]


class RepoScanner:
    def __init__(
        self,
        root: Path,
        included_globs: list[str] | None = None,
        excluded_dirs: set[str] | None = None,
        excluded_file_patterns: set[str] | None = None,
        max_file_size_bytes: int = 750_000,
        include_hidden: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.included_globs = included_globs or DEFAULT_INCLUDED_GLOBS
        self.excluded_dirs = excluded_dirs or DEFAULT_EXCLUDED_DIRS
        self.excluded_file_patterns = excluded_file_patterns or DEFAULT_EXCLUDED_FILE_PATTERNS
        self.max_file_size_bytes = max_file_size_bytes
        self.include_hidden = include_hidden

    def scan(self) -> list[FileRecord]:
        results: list[FileRecord] = []

        for path in self._iter_candidate_files():
            try:
                if not path.is_file():
                    continue

                stat = path.stat()

                if stat.st_size > self.max_file_size_bytes:
                    continue

                relative_path = path.relative_to(self.root).as_posix()

                if self._is_excluded_file(relative_path, path.name):
                    continue

                extension = path.suffix.lower()
                language = self._detect_language(path)

                if language is None:
                    continue

                record = FileRecord(
                    path=str(path),
                    relative_path=relative_path,
                    extension=extension,
                    language=language,
                    size_bytes=stat.st_size,
                    sha256=self._sha256_file(path),
                    modified_utc=datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                    category=self._categorize_file(path),
                    tags=self._infer_tags(path, language),
                )
                results.append(record)

            except (OSError, PermissionError):
                continue

        results.sort(key=lambda r: r.relative_path.lower())
        return results

    def _iter_candidate_files(self) -> Iterable[Path]:
        for current_root, dirnames, filenames in os.walk(self.root):
            current_root_path = Path(current_root)

            dirnames[:] = [
                d for d in dirnames
                if not self._should_skip_dir(current_root_path / d)
            ]

            for filename in filenames:
                file_path = current_root_path / filename

                if self._should_skip_file_path(file_path):
                    continue

                relative_path = file_path.relative_to(self.root).as_posix()

                if self._matches_included_globs(relative_path):
                    yield file_path

    def _matches_included_globs(self, relative_path: str) -> bool:
        return any(fnmatch.fnmatch(relative_path, pattern) for pattern in self.included_globs)

    def _should_skip_dir(self, path: Path) -> bool:
        name = path.name

        if name in self.excluded_dirs:
            return True

        if not self.include_hidden and name.startswith(".") and name not in {".github"}:
            return True

        return False

    def _should_skip_file_path(self, path: Path) -> bool:
        name = path.name

        if not self.include_hidden and name.startswith("."):
            return True

        return False

    def _is_excluded_file(self, relative_path: str, filename: str) -> bool:
        return any(
            fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(relative_path, pattern)
            for pattern in self.excluded_file_patterns
        )

    def _detect_language(self, path: Path) -> str | None:
        extension = path.suffix.lower()
        return SUPPORTED_EXTENSIONS.get(extension)

    def _categorize_file(self, path: Path) -> str:
        relative = path.relative_to(self.root).as_posix().lower()

        if relative.endswith(".vue"):
            return "component"
        if "/components/" in relative:
            return "component"
        if "/composables/" in relative:
            return "composable"
        if "/stores/" in relative or "store" in path.stem.lower():
            return "store"
        if "/services/" in relative:
            return "service"
        if "/controllers/" in relative:
            return "controller"
        if "/models/" in relative or "/entities/" in relative:
            return "model"
        if "/types/" in relative or path.name.endswith(".d.ts"):
            return "types"
        if "/docs/" in relative or path.suffix.lower() == ".md":
            return "documentation"
        if "/views/" in relative or "/pages/" in relative:
            return "view"
        if "/api/" in relative or "client" in path.stem.lower():
            return "api"
        return "source"

    def _infer_tags(self, path: Path, language: str) -> list[str]:
        relative = path.relative_to(self.root).as_posix().lower()
        tags = {language}

        if language in {"typescript", "javascript", "vue"}:
            tags.add("frontend")

        if language == "csharp":
            tags.add("backend")

        if path.suffix.lower() == ".vue":
            tags.add("vue")

        name_lower = path.name.lower()

        if "primevue" in relative or "primevue" in name_lower:
            tags.add("primevue")

        if "bryntum" in relative or "scheduler" in relative:
            tags.add("bryntum")

        if "/test/" in relative or "/tests/" in relative or name_lower.endswith(".spec.ts") or name_lower.endswith(".test.ts"):
            tags.add("test")

        if "/docs/" in relative or path.suffix.lower() == ".md":
            tags.add("docs")

        return sorted(tags)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()


def write_manifest(output_path: Path, records: list[FileRecord], root: Path) -> None:
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root.resolve()),
        "file_count": len(records),
        "files": [asdict(record) for record in records],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan a repo and build a manifest for KB ingestion.")
    parser.add_argument(
        "--root",
        required=True,
        help="Path to the repository root",
    )
    parser.add_argument(
        "--output",
        default="kb_exports/scan_manifest.json",
        help="Path to output manifest JSON",
    )
    parser.add_argument(
        "--max-file-size-bytes",
        type=int,
        default=750_000,
        help="Skip files larger than this size",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files/directories",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    root = Path(args.root)
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Invalid repo root: {root}")

    scanner = RepoScanner(
        root=root,
        max_file_size_bytes=args.max_file_size_bytes,
        include_hidden=args.include_hidden,
    )

    records = scanner.scan()
    output_path = Path(args.output)
    write_manifest(output_path, records, root)

    print(f"Scanned {len(records)} files")
    print(f"Manifest written to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
