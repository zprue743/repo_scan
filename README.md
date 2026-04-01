## repo_scan (Open WebUI Knowledge export)

This project scans a local repo and exports Markdown files designed for Open WebUI Knowledge Base ingestion.

### Offline-only

All scanning/chunking/export is **local**. No network access is used or required.

### Output

Exports are written to `kb_exports/openwebui/`:

- `frontend.md`: Typescript/Javascript/Vue sources (if any)
- `backend.md`: C# sources (if any)
- `docs.md`: Markdown docs (if any)
- `repo_index.md`: simple file listing

Each source file is embedded as its own `# path/to/file` section, with `## ...` subsections for symbols/parts. This preserves structure so Open WebUI’s **Markdown Header Splitting** works well.

### Open WebUI settings (recommended)

In **Admin Panel → Settings → Documents**:

- Enable **Markdown Header Splitting**
- Tune **Chunk Size**, **Chunk Overlap**, and **Chunk Min Size Target** to your model’s context window

### Running

Use the Python launcher on Windows:

```powershell
py repo_scanner.py --root "C:\path\to\repo" --output kb_exports/scan_manifest.json
py chunking/build_chunks.py
```

Then upload the generated `*.md` files from `kb_exports/openwebui/` into Open WebUI (Workspace → Knowledge).

### Quick validation checklist (after upload)

- Ask for a specific symbol, e.g. “Where is `RepoScanner` defined and what does it exclude?”
- Ask for a string literal or error message you know exists in the repo.
- Ask “What does `chunking/build_chunks.py` output?” and verify the answer cites the right `# path` section.
- If retrieval is noisy: decrease Chunk Size, increase Chunk Min Size Target, or split bundles further (e.g. `frontend_src.md` vs `frontend_tests.md`).

