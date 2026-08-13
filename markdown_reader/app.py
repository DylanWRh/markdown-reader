from __future__ import annotations

import argparse
import html
import math
import mimetypes
import os
import re
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from flask import Flask, abort, jsonify, render_template, request, send_file
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound


IGNORED_DIRECTORIES = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
}
MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel", "ftp"}


@dataclass(frozen=True)
class ReaderConfig:
    root: Path
    initial_file: Path


class DocumentRenderer(RendererHTML):
    """Markdown-it renderer with project-aware links and rich code blocks."""

    def __init__(self, root: Path, current_file: Path):
        super().__init__()
        self.root = root
        self.current_file = current_file
        self.slug_counts: dict[str, int] = {}
        self.headings: list[dict[str, Any]] = []

    @staticmethod
    def _slugify(value: str) -> str:
        value = re.sub(r"<[^>]+>", "", value)
        value = html.unescape(value).strip().lower()
        value = re.sub(r"[^\w\-\s\u4e00-\u9fff]", "", value, flags=re.UNICODE)
        value = re.sub(r"[\s_]+", "-", value).strip("-")
        return value or "section"

    def _unique_slug(self, value: str) -> str:
        base = self._slugify(value)
        count = self.slug_counts.get(base, 0)
        self.slug_counts[base] = count + 1
        return base if count == 0 else f"{base}-{count}"

    def heading_open(self, tokens, idx, options, env):
        token = tokens[idx]
        inline = tokens[idx + 1] if idx + 1 < len(tokens) else None
        title = (
            self.renderInlineAsText(inline.children or [], options, env).strip()
            if inline
            else ""
        )
        slug = self._unique_slug(title)
        token.attrSet("id", slug)
        token.attrJoin("class", "document-heading")
        self.headings.append(
            {"level": int(token.tag[1:]), "title": title, "id": slug}
        )
        return self.renderToken(tokens, idx, options, env)

    def fence(self, tokens, idx, options, env):
        token = tokens[idx]
        language = token.info.strip().split(maxsplit=1)[0] if token.info.strip() else ""
        if language.lower() == "mermaid":
            return (
                '<div class="diagram-shell" data-diagram-state="pending">'
                '<div class="diagram-label">Diagram</div>'
                f'<pre class="mermaid">{html.escape(token.content)}</pre>'
                "</div>"
            )

        try:
            lexer = get_lexer_by_name(language) if language else TextLexer()
        except ClassNotFound:
            lexer = TextLexer()
        formatted = highlight(
            token.content,
            lexer,
            HtmlFormatter(nowrap=True, cssclass="highlight"),
        )
        label = html.escape(language or "text")
        raw = html.escape(token.content, quote=True)
        return (
            '<div class="code-block">'
            f'<div class="code-toolbar"><span>{label}</span>'
            '<button class="copy-code" type="button" aria-label="Copy code">Copy</button></div>'
            f'<pre><code data-raw="{raw}">{formatted}</code></pre>'
            "</div>"
        )

    def image(self, tokens, idx, options, env):
        token = tokens[idx]
        src = token.attrGet("src") or ""
        resolved = resolve_project_reference(self.root, self.current_file, src)
        if resolved:
            token.attrSet("src", f"/api/raw?path={quote(resolved, safe='/')}")
            token.attrSet("data-source-path", resolved)
        token.attrSet("loading", "lazy")
        token.attrSet("decoding", "async")
        return super().image(tokens, idx, options, env)

    def link_open(self, tokens, idx, options, env):
        token = tokens[idx]
        href = token.attrGet("href") or ""
        split = urlsplit(href)
        if split.scheme.lower() in EXTERNAL_SCHEMES or href.startswith("//"):
            token.attrSet("target", "_blank")
            token.attrSet("rel", "noopener noreferrer")
            token.attrJoin("class", "external-link")
        elif href.startswith("#"):
            token.attrJoin("class", "document-link anchor-link")
            token.attrSet("data-anchor", unquote(href[1:]))
        else:
            resolved = resolve_project_reference(self.root, self.current_file, href)
            if resolved:
                target = safe_resolve(self.root, resolved)
                if target and target.is_dir():
                    for name in ("README.md", "index.md"):
                        candidate = target / name
                        if candidate.is_file():
                            resolved = candidate.relative_to(self.root).as_posix()
                            target = candidate
                            break
                if target and target.suffix.lower() in MARKDOWN_SUFFIXES:
                    token.attrJoin("class", "document-link cross-document-link")
                    token.attrSet("data-doc-path", resolved)
                    token.attrSet("data-anchor", unquote(split.fragment))
                    token.attrSet(
                        "href",
                        f"/?file={quote(resolved, safe='/')}"
                        + (f"#{quote(unquote(split.fragment))}" if split.fragment else ""),
                    )
                else:
                    token.attrJoin("class", "asset-link")
                    token.attrSet("href", f"/api/raw?path={quote(resolved, safe='/')}")
                    token.attrSet("target", "_blank")
        return self.renderToken(tokens, idx, options, env)


def safe_resolve(root: Path, relative_path: str | Path) -> Path | None:
    """Resolve a user-provided path while keeping it inside the project root."""
    try:
        candidate = (root / Path(str(relative_path))).resolve()
        candidate.relative_to(root)
        return candidate
    except (OSError, ValueError):
        return None


def resolve_project_reference(root: Path, current_file: Path, href: str) -> str | None:
    split = urlsplit(href)
    if split.scheme or href.startswith("//") or href.startswith("#"):
        return None
    path_part = unquote(split.path).replace("\\", "/")
    if not path_part:
        return current_file.relative_to(root).as_posix()
    base = current_file.parent
    try:
        target = (base / PurePosixPath(path_part)).resolve()
        target.relative_to(root)
        return target.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def make_markdown(renderer: RendererHTML) -> MarkdownIt:
    md = MarkdownIt(
        "commonmark",
        {"html": True, "linkify": True, "typographer": True},
        renderer_cls=lambda _parser: renderer,
    )
    md.enable(["table", "strikethrough"])
    md.use(footnote_plugin)
    md.use(tasklists_plugin, enabled=False, label=True)
    md.use(
        dollarmath_plugin,
        allow_space=True,
        allow_digits=True,
        renderer=lambda content, options: (
            f"\\[{html.escape(content)}\\]"
            if options["display_mode"]
            else f"\\({html.escape(content)}\\)"
        ),
    )
    return md


def extract_title(source: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", source, flags=re.MULTILINE)
    return re.sub(r"[*_`\[\]]", "", match.group(1)).strip() if match else fallback


def reading_stats(source: str) -> dict[str, int]:
    cleaned = re.sub(r"```.*?```", " ", source, flags=re.DOTALL)
    cleaned = re.sub(r"<[^>]+>|https?://\S+|[#*_>`|\[\]()]", " ", cleaned)
    latin_words = len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", cleaned))
    cjk_chars = len(re.findall(r"[\u3400-\u9fff]", cleaned))
    units = latin_words + cjk_chars
    minutes = max(1, math.ceil(latin_words / 220 + cjk_chars / 450))
    return {"words": units, "minutes": minutes}


def render_document(config: ReaderConfig, relative_path: str) -> dict[str, Any]:
    target = safe_resolve(config.root, relative_path)
    if not target or not target.is_file() or target.suffix.lower() not in MARKDOWN_SUFFIXES:
        raise FileNotFoundError(relative_path)
    source = target.read_text(encoding="utf-8-sig")
    renderer = DocumentRenderer(config.root, target)
    md = make_markdown(renderer)
    rendered = md.render(source)
    stat = target.stat()
    return {
        "path": target.relative_to(config.root).as_posix(),
        "title": extract_title(source, target.stem.replace("-", " ").title()),
        "html": rendered,
        "toc": renderer.headings,
        "stats": reading_stats(source),
        "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
    }


def heading_slug(text: str) -> str:
    return DocumentRenderer._slugify(text)


def preview_source(source: str, anchor: str) -> str:
    lines = source.splitlines()
    if not anchor:
        return "\n".join(lines[:32])

    counts: dict[str, int] = {}
    start = None
    level = 7
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        base = heading_slug(match.group(2))
        count = counts.get(base, 0)
        counts[base] = count + 1
        slug = base if count == 0 else f"{base}-{count}"
        if slug == anchor or unquote(anchor) == match.group(2).strip():
            start = index
            level = len(match.group(1))
            break
    if start is None:
        return "\n".join(lines[:32])
    end = min(len(lines), start + 42)
    for index in range(start + 1, end):
        match = re.match(r"^(#{1,6})\s+", lines[index])
        if match and len(match.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[start:end])


def build_tree(root: Path, directory: Path | None = None) -> list[dict[str, Any]]:
    directory = directory or root
    nodes: list[dict[str, Any]] = []
    try:
        children = list(directory.iterdir())
    except OSError:
        return nodes
    children.sort(key=lambda item: (not item.is_dir(), item.name.lower()))
    for child in children:
        if child.name.startswith(".") or child.name in IGNORED_DIRECTORIES:
            continue
        try:
            relative = child.relative_to(root).as_posix()
            if child.is_dir():
                descendants = build_tree(root, child)
                if descendants:
                    nodes.append(
                        {"name": child.name, "path": relative, "type": "folder", "children": descendants}
                    )
            elif child.is_file():
                nodes.append(
                    {
                        "name": child.name,
                        "path": relative,
                        "type": "markdown" if child.suffix.lower() in MARKDOWN_SUFFIXES else "file",
                        "extension": child.suffix.lower().lstrip("."),
                    }
                )
        except OSError:
            continue
    return nodes


def find_initial_markdown(root: Path, requested: str | None = None) -> Path:
    """Choose the first document shown for a project directory."""
    if requested:
        candidate = safe_resolve(root, requested)
        if not candidate or not candidate.is_file() or candidate.suffix.lower() not in MARKDOWN_SUFFIXES:
            raise ValueError(f"Initial Markdown file not found inside the project: {requested}")
        return candidate

    for name in ("README.md", "README.markdown", "index.md", "INDEX.md"):
        candidate = root / name
        if candidate.is_file():
            return candidate.resolve()

    documents: list[Path] = []
    for current, directories, files in os.walk(root):
        directories[:] = sorted(
            (
                name
                for name in directories
                if not name.startswith(".") and name not in IGNORED_DIRECTORIES
            ),
            key=str.lower,
        )
        for name in sorted(files, key=str.lower):
            candidate = Path(current) / name
            if candidate.suffix.lower() in MARKDOWN_SUFFIXES:
                documents.append(candidate.resolve())
    documents.sort(key=lambda path: path.relative_to(root).as_posix().lower())
    if not documents:
        raise FileNotFoundError(f"No Markdown files found in directory: {root}")
    return documents[0].resolve()


def create_app(config: ReaderConfig) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["READER_CONFIG"] = config

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob: https: http:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; font-src 'self' data:; connect-src 'self'"
        )
        return response

    @app.get("/")
    def index():
        initial = config.initial_file.relative_to(config.root).as_posix()
        requested = request.args.get("file", initial)
        resolved = safe_resolve(config.root, requested)
        if not resolved or not resolved.is_file() or resolved.suffix.lower() not in MARKDOWN_SUFFIXES:
            requested = initial
        return render_template(
            "index.html",
            project_name=config.root.name,
            initial_file=requested,
        )

    @app.get("/api/project")
    def project():
        return jsonify(
            {
                "name": config.root.name,
                "root": str(config.root),
                "initialFile": config.initial_file.relative_to(config.root).as_posix(),
                "tree": build_tree(config.root),
            }
        )

    @app.get("/api/document")
    def document():
        relative_path = request.args.get("path", "")
        try:
            return jsonify(render_document(config, relative_path))
        except (FileNotFoundError, OSError, UnicodeError):
            abort(404)

    @app.get("/api/preview")
    def preview():
        relative_path = request.args.get("path", "")
        anchor = request.args.get("anchor", "")
        target = safe_resolve(config.root, relative_path)
        if not target or not target.is_file() or target.suffix.lower() not in MARKDOWN_SUFFIXES:
            abort(404)
        try:
            source = target.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            abort(404)
        excerpt = preview_source(source, anchor)
        renderer = DocumentRenderer(config.root, target)
        rendered = make_markdown(renderer).render(excerpt)
        return jsonify(
            {
                "path": target.relative_to(config.root).as_posix(),
                "title": extract_title(excerpt, extract_title(source, target.stem)),
                "html": rendered,
            }
        )

    @app.get("/api/raw")
    def raw_file():
        relative_path = request.args.get("path", "")
        target = safe_resolve(config.root, relative_path)
        if not target or not target.is_file():
            abort(404)
        guessed, _ = mimetypes.guess_type(target.name)
        return send_file(target, mimetype=guessed, conditional=True)

    return app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A focused, local-first Markdown reader with project navigation."
    )
    parser.add_argument("directory", help="Project directory to read")
    parser.add_argument(
        "--initial",
        metavar="FILE",
        help="Initial Markdown file relative to the project directory",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Listening host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Listening port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Project directory not found: {root}")
    try:
        initial_file = find_initial_markdown(root, args.initial)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    config = ReaderConfig(root=root, initial_file=initial_file)
    app = create_app(config)
    url = f"http://{args.host}:{args.port}/?file={quote(initial_file.relative_to(root).as_posix(), safe='/')}"
    print(f"\n  Markdown Reader  {url}")
    print(f"  Project root     {root}\n")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
