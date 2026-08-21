from __future__ import annotations

import argparse
import codecs
import ctypes
import hashlib
import html
import json
import math
import mimetypes
import os
import re
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from threading import RLock
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
MAX_MARKDOWN_BYTES = 5 * 1024 * 1024
HTML_ASSET_ATTRIBUTES = {
    "audio": {"src"},
    "embed": {"src"},
    "img": {"src"},
    "object": {"data"},
    "source": {"src"},
    "track": {"src"},
    "video": {"poster", "src"},
}


@dataclass(frozen=True)
class ReaderConfig:
    root: Path
    initial_file: Path


def default_workspace_state_file() -> Path:
    """Return the per-user file used to remember recently opened workspaces."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "markdown-reader" / "workspaces.json"


class WorkspaceManager:
    """Own the active project root and a small persistent recent-workspace list."""

    def __init__(
        self,
        config: ReaderConfig | None,
        state_file: Path | None = None,
        max_recent: int = 8,
        browse_start: Path | None = None,
    ) -> None:
        self._lock = RLock()
        self._config = (
            ReaderConfig(config.root.resolve(), config.initial_file.resolve())
            if config
            else None
        )
        self._state_file = state_file
        self._max_recent = max_recent
        self._browse_start = (browse_start or Path.cwd()).resolve()
        self._recent = self._load_recent()
        if self._config:
            self._remember(self._config.root)

    @property
    def current(self) -> ReaderConfig | None:
        with self._lock:
            return self._config

    def switch(self, directory: str | Path) -> ReaderConfig:
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Workspace directory not found: {root}")
        try:
            initial_file = find_initial_markdown(root)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        with self._lock:
            self._config = ReaderConfig(root=root, initial_file=initial_file)
            self._remember(root)
            return self._config

    def recent(self) -> list[dict[str, Any]]:
        with self._lock:
            current = self._config.root if self._config else None
            result = []
            for value in self._recent:
                root = Path(value)
                result.append(
                    {
                        "name": root.name or str(root),
                        "path": str(root),
                        "available": root.is_dir(),
                        "current": root == current,
                    }
                )
            return result

    def browse_start(self) -> Path:
        with self._lock:
            if self._config:
                return self._config.root
            for value in self._recent:
                candidate = Path(value)
                if candidate.is_dir():
                    return candidate
            return self._browse_start

    def _remember(self, root: Path) -> None:
        value = str(root)
        self._recent = [value, *(item for item in self._recent if item != value)][
            : self._max_recent
        ]
        self._save_recent()

    def _load_recent(self) -> list[str]:
        if not self._state_file or not self._state_file.is_file():
            return []
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
            values = payload.get("recent", [])
            return [str(Path(value).expanduser().resolve()) for value in values if value]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []

    def _save_recent(self) -> None:
        if not self._state_file:
            return
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._state_file.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"recent": self._recent}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self._state_file)
        except OSError:
            # Remembering recents is a convenience; reading must still work if the
            # per-user state directory is unavailable or read-only.
            pass


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

    def html_block(self, tokens, idx, options, env):
        return rewrite_html_asset_references(
            self.root, self.current_file, tokens[idx].content
        )

    def html_inline(self, tokens, idx, options, env):
        return rewrite_html_asset_references(
            self.root, self.current_file, tokens[idx].content
        )

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


class LocalAssetHTMLRewriter(HTMLParser):
    """Rewrite local asset attributes in raw Markdown HTML to the file API."""

    def __init__(self, root: Path, current_file: Path) -> None:
        super().__init__(convert_charrefs=False)
        self.root = root
        self.current_file = current_file
        self.parts: list[str] = []

    def _start_tag(self, tag: str, attrs, self_closing: bool) -> None:
        allowed = HTML_ASSET_ATTRIBUTES.get(tag.lower())
        if not allowed:
            self.parts.append(self.get_starttag_text() or f"<{tag}>")
            return

        rewritten = []
        changed = False
        for name, value in attrs:
            if value is not None and name.lower() in allowed:
                resolved = resolve_project_reference(self.root, self.current_file, value)
                if resolved:
                    value = f"/api/raw?path={quote(resolved, safe='/')}"
                    changed = True
            rewritten.append((name, value))

        if not changed:
            self.parts.append(self.get_starttag_text() or f"<{tag}>")
            return

        attributes = "".join(
            f" {name}" if value is None else f' {name}="{html.escape(value, quote=True)}"'
            for name, value in rewritten
        )
        ending = " />" if self_closing else ">"
        self.parts.append(f"<{tag}{attributes}{ending}")

    def handle_starttag(self, tag: str, attrs) -> None:
        self._start_tag(tag, attrs, False)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self._start_tag(tag, attrs, True)

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self.parts.append(f"<?{data}>")


def rewrite_html_asset_references(
    root: Path, current_file: Path, markup: str
) -> str:
    rewriter = LocalAssetHTMLRewriter(root, current_file)
    rewriter.feed(markup)
    rewriter.close()
    return "".join(rewriter.parts)


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


def document_source(config: ReaderConfig, relative_path: str) -> dict[str, Any]:
    """Read editable Markdown source and return a content-based version token."""
    target = safe_resolve(config.root, relative_path)
    if not target or not target.is_file() or target.suffix.lower() not in MARKDOWN_SUFFIXES:
        raise FileNotFoundError(relative_path)
    raw = target.read_bytes()
    if len(raw) > MAX_MARKDOWN_BYTES:
        raise OverflowError(relative_path)
    return {
        "path": target.relative_to(config.root).as_posix(),
        "source": raw.decode("utf-8-sig"),
        "version": hashlib.sha256(raw).hexdigest(),
        "workspace": str(config.root),
    }


class DocumentConflictError(RuntimeError):
    """Raised when a document changed after the editor loaded it."""


def save_document_source(
    config: ReaderConfig,
    relative_path: str,
    source: str,
    expected_version: str,
) -> dict[str, Any]:
    """Atomically save Markdown if its current version still matches."""
    target = safe_resolve(config.root, relative_path)
    if not target or not target.is_file() or target.suffix.lower() not in MARKDOWN_SUFFIXES:
        raise FileNotFoundError(relative_path)

    current = target.read_bytes()
    if hashlib.sha256(current).hexdigest() != expected_version:
        raise DocumentConflictError(relative_path)

    encoded = source.encode("utf-8")
    if current.startswith(codecs.BOM_UTF8):
        encoded = codecs.BOM_UTF8 + encoded
    if len(encoded) > MAX_MARKDOWN_BYTES:
        raise OverflowError(relative_path)

    temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_bytes(encoded)
        temporary.chmod(target.stat().st_mode)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected_version:
            raise DocumentConflictError(relative_path)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return document_source(config, relative_path)


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


def project_payload(config: ReaderConfig) -> dict[str, Any]:
    return {
        "name": config.root.name or str(config.root),
        "root": str(config.root),
        "initialFile": config.initial_file.relative_to(config.root).as_posix(),
        "tree": build_tree(config.root),
        "initialized": True,
    }


def empty_project_payload() -> dict[str, Any]:
    return {
        "name": "选择工作区",
        "root": "",
        "initialFile": "",
        "tree": [],
        "initialized": False,
    }


def list_windows_drives() -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    return [
        {"name": f"{chr(65 + index)}:", "path": f"{chr(65 + index)}:\\"}
        for index in range(26)
        if bitmask & (1 << index)
    ]


def browse_directory(path: Path) -> dict[str, Any]:
    root = path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Directory not found: {root}")
    directories = []
    try:
        children = sorted(
            (
                child
                for child in root.iterdir()
                if child.is_dir() and not child.name.startswith(".")
            ),
            key=lambda child: child.name.lower(),
        )
    except (OSError, PermissionError) as exc:
        raise ValueError(f"Cannot access directory: {root}") from exc
    for child in children:
        directories.append({"name": child.name, "path": str(child)})
    try:
        has_markdown = any(
            child.is_file() and child.suffix.lower() in MARKDOWN_SUFFIXES
            for child in root.iterdir()
        )
    except (OSError, PermissionError):
        has_markdown = False
    parent = None if root.parent == root else str(root.parent)
    return {
        "path": str(root),
        "parent": parent,
        "directories": directories,
        "drives": list_windows_drives() if parent is None else [],
        "hasMarkdown": has_markdown,
    }


def create_app(
    config: ReaderConfig | None,
    *,
    state_file: Path | None = None,
    browse_start: Path | None = None,
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    manager = WorkspaceManager(
        config,
        state_file=state_file if state_file is not None else default_workspace_state_file(),
        browse_start=browse_start,
    )
    switch_token = secrets.token_urlsafe(24)
    mutation_lock = RLock()
    app.config["WORKSPACE_MANAGER"] = manager
    app.config["WORKSPACE_SWITCH_TOKEN"] = switch_token

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
        config = manager.current
        if not config:
            return render_template(
                "index.html",
                project_name="选择工作区",
                initial_file="",
                workspace_switch_token=switch_token,
            )
        initial = config.initial_file.relative_to(config.root).as_posix()
        requested = request.args.get("file", initial)
        resolved = safe_resolve(config.root, requested)
        if not resolved or not resolved.is_file() or resolved.suffix.lower() not in MARKDOWN_SUFFIXES:
            requested = initial
        return render_template(
            "index.html",
            project_name=config.root.name,
            initial_file=requested,
            workspace_switch_token=switch_token,
        )

    @app.get("/api/project")
    def project():
        config = manager.current
        return jsonify(project_payload(config) if config else empty_project_payload())

    @app.get("/api/workspaces")
    def workspaces():
        return jsonify({"recent": manager.recent()})

    @app.get("/api/directories")
    def directories():
        if request.headers.get("X-Workspace-Token") != switch_token:
            abort(403)
        requested = request.args.get("path")
        target = Path(requested).expanduser() if requested else manager.browse_start()
        try:
            return jsonify(browse_directory(target))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/workspace")
    def switch_workspace():
        if request.headers.get("X-Workspace-Token") != switch_token:
            abort(403)
        payload = request.get_json(silent=True) or {}
        directory = payload.get("path")
        if not isinstance(directory, str) or not directory.strip():
            return jsonify({"error": "请输入工作区目录。"}), 400
        try:
            with mutation_lock:
                selected = manager.switch(directory.strip())
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(
            {
                "project": project_payload(selected),
                "recent": manager.recent(),
            }
        )

    @app.get("/api/document")
    def document():
        config = manager.current
        if not config:
            abort(409)
        relative_path = request.args.get("path", "")
        try:
            return jsonify(render_document(config, relative_path))
        except (FileNotFoundError, OSError, UnicodeError):
            abort(404)

    @app.get("/api/source")
    def source():
        if request.headers.get("X-Workspace-Token") != switch_token:
            abort(403)
        config = manager.current
        if not config:
            abort(409)
        try:
            return jsonify(document_source(config, request.args.get("path", "")))
        except OverflowError:
            return jsonify({"error": "Markdown 文件超过 5 MiB，无法在编辑器中打开。"}), 413
        except (FileNotFoundError, OSError, UnicodeError):
            abort(404)

    @app.put("/api/source")
    def save_source():
        if request.headers.get("X-Workspace-Token") != switch_token:
            abort(403)
        payload = request.get_json(silent=True) or {}
        relative_path = payload.get("path")
        source_text = payload.get("source")
        expected_version = payload.get("version")
        expected_workspace = payload.get("workspace")
        if not all(isinstance(value, str) for value in (relative_path, source_text, expected_version, expected_workspace)):
            return jsonify({"error": "保存请求缺少必要字段。"}), 400
        try:
            encoded_size = len(source_text.encode("utf-8"))
        except UnicodeError:
            return jsonify({"error": "Markdown 内容不是有效的 UTF-8 文本。"}), 400
        if encoded_size > MAX_MARKDOWN_BYTES:
            return jsonify({"error": "Markdown 文件超过 5 MiB，无法在编辑器中保存。"}), 413
        try:
            with mutation_lock:
                config = manager.current
                if not config:
                    return jsonify({"error": "请先选择工作区。"}), 409
                if expected_workspace != str(config.root):
                    return jsonify({"error": "工作区已切换，请重新打开文档后再编辑。"}), 409
                saved = save_document_source(
                    config,
                    relative_path,
                    source_text,
                    expected_version,
                )
                saved["document"] = render_document(config, relative_path)
                return jsonify(saved)
        except DocumentConflictError:
            return jsonify({"error": "文件已被其他程序修改。请取消编辑并重新载入后再试。"}), 409
        except OverflowError:
            return jsonify({"error": "Markdown 文件超过 5 MiB，无法在编辑器中保存。"}), 413
        except (FileNotFoundError, OSError, UnicodeError):
            abort(404)

    @app.get("/api/preview")
    def preview():
        config = manager.current
        if not config:
            abort(409)
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
        config = manager.current
        if not config:
            abort(409)
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
    parser.add_argument(
        "directory",
        nargs="?",
        help="Project directory to read (omit to choose one in the browser)",
    )
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
    config = None
    if args.directory:
        root = Path(args.directory).expanduser().resolve()
        if not root.is_dir():
            raise SystemExit(f"Project directory not found: {root}")
        try:
            initial_file = find_initial_markdown(root, args.initial)
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        config = ReaderConfig(root=root, initial_file=initial_file)
    elif args.initial:
        raise SystemExit("--initial requires a project directory")
    app = create_app(config, browse_start=Path.cwd())
    url = f"http://{args.host}:{args.port}/"
    if config:
        url += f"?file={quote(config.initial_file.relative_to(config.root).as_posix(), safe='/')}"
    print(f"\n  Markdown Reader  {url}")
    print(f"  Project root     {config.root if config else 'Choose in browser'}\n")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
