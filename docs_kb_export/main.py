from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


DEFAULT_BRYNTUM_ROOT = "https://bryntum.com/docs/scheduler-pro/"
DEFAULT_PRIMEVUE_ROOT = "https://primevue.org/"

DEFAULT_TARGET_BYTES = 750 * 1024
DEFAULT_MAX_PAGES = 2000
DEFAULT_SLEEP_S = 0.2
DEFAULT_TIMEOUT_S = 30


@dataclass(frozen=True, slots=True)
class Page:
    url: str
    title: str
    markdown: str
    sha256: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Crawl docs and export Open WebUI-friendly markdown parts.")
    p.add_argument("--bryntum-root", default=DEFAULT_BRYNTUM_ROOT)
    p.add_argument("--primevue-root", default=DEFAULT_PRIMEVUE_ROOT)
    p.add_argument("--target-bytes", type=int, default=DEFAULT_TARGET_BYTES)
    p.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    p.add_argument("--sleep-s", type=float, default=DEFAULT_SLEEP_S)
    p.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    p.add_argument("--output-dir", default=str(Path(__file__).parent / "output"))
    p.add_argument("--refresh", action="store_true", help="Ignore cache and re-fetch everything.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cache_path = out_dir / "cache.json"
    cache = _load_cache(cache_path) if not args.refresh else {}

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "docs_kb_export/1.0 (OpenWebUI knowledge export; polite crawler)",
            "Accept": "text/html,application/xhtml+xml",
        }
    )

    jobs = [
        ("bryntum", "bryntum_scheduler_pro", args.bryntum_root),
        ("primevue", "primevue", args.primevue_root),
    ]

    all_pages: dict[str, list[Page]] = {}

    for key, product_id, root in jobs:
        pages, cache = crawl_docs(
            session=session,
            root_url=root,
            product_id=product_id,
            cache=cache,
            max_pages=args.max_pages,
            sleep_s=args.sleep_s,
            timeout_s=args.timeout_s,
        )
        all_pages[key] = pages
        write_outputs(
            out_dir=out_dir,
            prefix=key,
            product_id=product_id,
            pages=pages,
            target_bytes=args.target_bytes,
        )

    _save_cache(cache_path, cache)

    print(f"Wrote outputs to: {out_dir.resolve()}")
    for key, pages in all_pages.items():
        print(f"{key}: {len(pages)} pages")


def crawl_docs(
    *,
    session: requests.Session,
    root_url: str,
    product_id: str,
    cache: dict,
    max_pages: int,
    sleep_s: float,
    timeout_s: int,
) -> tuple[list[Page], dict]:
    root_url = _canonical_url(root_url)
    root_parsed = urlparse(root_url)
    allow_host = root_parsed.netloc
    allow_prefix = root_parsed.path.rstrip("/") + "/"

    seen: set[str] = set()
    q: deque[str] = deque([root_url])
    pages: list[Page] = []

    while q and len(seen) < max_pages:
        url = q.popleft()
        url = _canonical_url(url)
        if url in seen:
            continue
        seen.add(url)

        if not _in_scope(url, allow_host, allow_prefix):
            continue

        html = None
        cached = cache.get(url)
        if cached and isinstance(cached, dict) and "html_sha256" in cached and "html" in cached:
            html = cached.get("html")

        if html is None:
            try:
                resp = session.get(url, timeout=timeout_s)
                if resp.status_code != 200:
                    continue
                ctype = resp.headers.get("content-type", "")
                if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
                    continue
                html = resp.text
                time.sleep(max(0.0, sleep_s))
            except requests.RequestException:
                continue

        if not html:
            continue

        html_sha = _sha256_text(html)
        cache[url] = {"html_sha256": html_sha, "html": html}

        md_title, md = html_to_markdown(html, base_url=url, product_id=product_id)
        if not md.strip():
            continue

        page_md = _format_page_markdown(product_id, md_title, url, md)
        pages.append(Page(url=url, title=md_title, markdown=page_md, sha256=_sha256_text(page_md)))

        for link in extract_links(html, base_url=url):
            link = _canonical_url(link)
            if link and link not in seen and _in_scope(link, allow_host, allow_prefix):
                q.append(link)

    pages.sort(key=lambda p: p.url)
    return pages, cache


def extract_links(html: str, *, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href:
            continue
        if href.startswith("#"):
            continue
        if href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        abs_url = urljoin(base_url, href)
        links.append(abs_url)
    return links


def html_to_markdown(html: str, *, base_url: str, product_id: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    for tag_name in ("nav", "header", "footer", "aside"):
        for t in soup.find_all(tag_name):
            t.decompose()

    main = soup.find("main") or soup.find("article")
    if main is None:
        main = soup.body or soup

    title = _extract_title(soup) or product_id
    md = _render_block_children(main, base_url=base_url).strip()
    md = _collapse_blank_lines(md)
    return title, md


def _extract_title(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    if isinstance(h1, Tag):
        text = h1.get_text(" ", strip=True)
        if text:
            return text
    if soup.title and soup.title.string:
        t = str(soup.title.string).strip()
        return t or None
    return None


def _render_block_children(node: Tag, *, base_url: str) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            continue
        if not isinstance(child, Tag):
            continue
        chunk = _render_tag(child, base_url=base_url)
        if chunk:
            parts.append(chunk)
    return "\n\n".join([p for p in parts if p.strip()])


def _render_tag(tag: Tag, *, base_url: str) -> str:
    name = tag.name.lower()

    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = int(name[1])
        text = tag.get_text(" ", strip=True)
        if not text:
            return ""
        return ("#" * level) + " " + text

    if name == "p":
        return _render_inline(tag, base_url=base_url).strip()

    if name in {"ul", "ol"}:
        return _render_list(tag, base_url=base_url)

    if name == "pre":
        code = tag.find("code")
        if code and isinstance(code, Tag):
            lang = _language_from_code_tag(code)
            text = code.get_text("\n", strip=False).rstrip("\n")
        else:
            lang = ""
            text = tag.get_text("\n", strip=False).rstrip("\n")
        return _fence(text, lang)

    if name == "code":
        return f"`{tag.get_text(' ', strip=True)}`"

    if name == "table":
        return tag.get_text(" ", strip=True)

    if name in {"div", "section", "article", "main"}:
        return _render_block_children(tag, base_url=base_url)

    if name in {"blockquote"}:
        inner = _render_block_children(tag, base_url=base_url)
        lines = ["> " + line if line else ">" for line in inner.splitlines()]
        return "\n".join(lines).strip()

    if name == "hr":
        return "---"

    return ""


def _render_list(tag: Tag, *, base_url: str) -> str:
    ordered = tag.name.lower() == "ol"
    lines: list[str] = []
    index = 1
    for li in tag.find_all("li", recursive=False):
        text = _render_inline(li, base_url=base_url).strip()
        prefix = f"{index}. " if ordered else "- "
        if text:
            lines.append(prefix + text)
        index += 1
    return "\n".join(lines).strip()


def _render_inline(tag: Tag, *, base_url: str) -> str:
    out: list[str] = []

    for child in tag.descendants:
        if isinstance(child, NavigableString):
            txt = str(child)
            if txt and not txt.isspace():
                out.append(txt)
            continue
        if not isinstance(child, Tag):
            continue
        if child.name and child.name.lower() == "br":
            out.append("\n")
        if child.name and child.name.lower() == "code":
            out.append(f"`{child.get_text(' ', strip=True)}`")
        if child.name and child.name.lower() == "a":
            href = child.get("href", "").strip()
            text = child.get_text(" ", strip=True) or href
            if href:
                abs_url = urljoin(base_url, href)
                out.append(f"[{text}]({abs_url})")
            else:
                out.append(text)

    text = "".join(out)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _language_from_code_tag(code: Tag) -> str:
    cls = " ".join(code.get("class", [])).lower()
    for prefix in ("language-", "lang-"):
        m = re.search(rf"{prefix}([a-z0-9_+-]+)", cls)
        if m:
            return m.group(1)
    return ""


def _fence(text: str, lang: str) -> str:
    text = text.rstrip()
    fence = "```" + (lang or "")
    return f"{fence}\n{text}\n```"


def _format_page_markdown(product_id: str, title: str, url: str, body_md: str) -> str:
    lines: list[str] = []
    lines.append(f"# {product_id} — {title}")
    lines.append("")
    lines.append(f"source: {url}")
    lines.append(f"product: {product_id}")
    lines.append("")
    lines.append(body_md.strip())
    return _collapse_blank_lines("\n".join(lines)).rstrip() + "\n"


def write_outputs(
    *,
    out_dir: Path,
    prefix: str,
    product_id: str,
    pages: list[Page],
    target_bytes: int,
) -> None:
    index_path = out_dir / f"{prefix}_repo_index.md"
    index_lines = [f"# {product_id} repo_index", "", f"- page_count: {len(pages)}", "", "## pages", ""]
    for p in pages:
        index_lines.append(f"- [{p.title}]({p.url})")
    index_path.write_text("\n".join(index_lines).rstrip() + "\n", encoding="utf-8")

    part_idx = 1
    buf: list[str] = []
    buf_bytes = 0

    def flush() -> None:
        nonlocal part_idx, buf, buf_bytes
        if not buf:
            return
        part_path = out_dir / f"{prefix}_part_{part_idx:03d}.md"
        part_path.write_text("\n\n".join(buf).rstrip() + "\n", encoding="utf-8")
        part_idx += 1
        buf = []
        buf_bytes = 0

    for p in pages:
        content = p.markdown
        content_bytes = len(content.encode("utf-8"))

        if content_bytes > target_bytes:
            flush()
            chunks = _split_oversize_page(content, target_bytes)
            for chunk in chunks:
                chunk_bytes = len(chunk.encode("utf-8"))
                if chunk_bytes > target_bytes:
                    part_path = out_dir / f"{prefix}_part_{part_idx:03d}.md"
                    part_path.write_text(chunk.rstrip() + "\n", encoding="utf-8")
                    print(
                        f"WARNING: oversized chunk for {p.url} is ~{chunk_bytes} bytes; wrote as its own part."
                    )
                    part_idx += 1
                else:
                    if buf and (buf_bytes + chunk_bytes) > target_bytes:
                        flush()
                    buf.append(chunk)
                    buf_bytes += chunk_bytes
            continue

        if buf and (buf_bytes + content_bytes) > target_bytes:
            flush()
        buf.append(content)
        buf_bytes += content_bytes

    flush()


def _split_oversize_page(page_md: str, target_bytes: int) -> list[str]:
    # Keep header block, then split on H2 boundaries.
    lines = page_md.splitlines()
    header: list[str] = []
    body_lines: list[str] = []
    in_header = True
    for line in lines:
        if in_header and line.startswith("## "):
            in_header = False
        if in_header:
            header.append(line)
        else:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    if not body:
        return [page_md]

    sections = re.split(r"(?m)^(## .+)$", body)
    # re.split yields: [pre, h2, rest, h2, rest...]
    chunks: list[str] = []
    if len(sections) == 1:
        return [page_md]

    pre = sections[0].strip()
    pairs = list(zip(sections[1::2], sections[2::2]))
    if pre:
        pairs.insert(0, ("## content", pre))

    current: list[str] = ["\n".join(header).strip(), ""]
    current_bytes = len("\n".join(current).encode("utf-8"))

    def push_current() -> None:
        nonlocal current, current_bytes
        txt = _collapse_blank_lines("\n".join(current)).rstrip() + "\n"
        chunks.append(txt)
        current = ["\n".join(header).strip(), ""]
        current_bytes = len("\n".join(current).encode("utf-8"))

    for h2, rest in pairs:
        section_text = _collapse_blank_lines("\n".join([h2.strip(), "", rest.strip()])).rstrip() + "\n"
        sec_bytes = len(section_text.encode("utf-8"))

        if current and (current_bytes + sec_bytes) > target_bytes and len(current) > 2:
            push_current()

        current.append(section_text.rstrip())
        current_bytes += sec_bytes

    if len(current) > 2:
        push_current()

    return chunks or [page_md]


def _canonical_url(url: str) -> str:
    try:
        p = urlparse(url)
    except ValueError:
        return ""
    if not p.scheme or not p.netloc:
        return ""
    # Drop fragment, normalize path.
    path = re.sub(r"/{2,}", "/", p.path)
    if not path:
        path = "/"
    return urlunparse((p.scheme, p.netloc, path, "", p.query, ""))


def _in_scope(url: str, allow_host: str, allow_prefix: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.netloc != allow_host:
        return False
    return p.path.startswith(allow_prefix)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _collapse_blank_lines(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _load_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    except json.JSONDecodeError:
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

