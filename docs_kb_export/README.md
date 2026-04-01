## docs_kb_export (standalone Open WebUI Knowledge docs exporter)

This folder is a **standalone** tool to crawl public documentation sites (Bryntum Scheduler Pro + PrimeVue v4), convert pages to Markdown, and split output into <1MB-friendly part files for manual upload into Open WebUI Knowledge.

It is intentionally **isolated** from the repo scanner/chunker code in the project root.

### Install

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Run (default roots)

```powershell
py main.py
```

### Outputs

Written under `docs_kb_export/output/`:

- `bryntum_repo_index.md`
- `bryntum_part_001.md`, `bryntum_part_002.md`, ...
- `primevue_repo_index.md`
- `primevue_part_001.md`, `primevue_part_002.md`, ...

### Open WebUI notes

In Open WebUI Admin Panel → Settings → Documents:

- Enable **Markdown Header Splitting**
- Tune chunk size / overlap / min target for your model context window

