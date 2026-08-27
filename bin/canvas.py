#!/usr/bin/env python3
"""Render QMD-indexed Brain Markdown as an offline force-directed graph.

    bin/canvas.py                         # serve the shared graph with live reload
    bin/canvas.py --collection brain      # select a collection (repeatable)
    bin/canvas.py --all-collections       # every include-by-default collection
    bin/canvas.py --scope all             # explicitly include private local knowledge
    bin/canvas.py --no-open               # serve without launching a browser
    bin/canvas.py --output canvas.html    # explicit offline single-file export
    bin/canvas.py --dry-run               # report counts without writing

The default view contains the shared knowledge layer. Nodes are documents plus
small tag nodes. Independently togglable edges represent Markdown links and
wikilinks, document-to-tag membership, and semantic similarity from QMD's own
vector index.

The primary interface is a localhost application with automatic reload for UI
source and QMD index changes. An explicit single-file export inlines D3 for
offline use. Markdown remains canonical, and semantic decoding degrades with
one warning when QMD's internal, undocumented vector storage changes shape.
"""

from __future__ import annotations

import argparse
import base64
import html
import http.server
import json
import math
import posixpath
import re
import sqlite3
import struct
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from okf import parse


SHARED_FOLDERS = {
    "patterns",
    "lessons",
    "decisions",
    "concepts",
    "snippets",
    "sources",
    "infra",
}
ROOT_SHARED_FILES = {"MEMORY.md"}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
VECTOR_DIMENSION = re.compile(r"embedding\s+float\[(\d+)\]", re.IGNORECASE)


@dataclass(frozen=True)
class Collection:
    name: str
    path: str
    include_by_default: bool


@dataclass
class DocumentNode:
    id: str
    label: str
    kind: str
    category: str
    collection: str
    path: str
    title: str
    description: str
    tags: list[str]
    url: str
    date: str
    project: str
    is_session: bool
    content_hash: str


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str
    score: float | None = None


def file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


def is_local_host_header(value: str) -> bool:
    host = value.strip().lower()
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host.rstrip(".") in {"localhost", "127.0.0.1", "::1"}


class CanvasState:
    """Thread-safe graph state plus source/index change detection."""

    def __init__(
        self,
        graph: dict[str, object],
        d3_source: str,
        watched_paths: list[Path],
        rebuild,
    ) -> None:
        self._graph = graph
        self._d3_source = d3_source
        self._watched_paths = watched_paths
        self._rebuild = rebuild
        self._signatures = {path: file_signature(path) for path in watched_paths}
        self._lock = threading.Lock()
        self._version = 1
        self._last_error = ""

    def snapshot(self) -> tuple[dict[str, object], str, int]:
        with self._lock:
            return self._graph, self._d3_source, self._version

    def refresh_if_changed(self) -> None:
        signatures = {path: file_signature(path) for path in self._watched_paths}
        changed = [path for path in self._watched_paths if signatures[path] != self._signatures[path]]
        if not changed:
            return
        with self._lock:
            graph = self._graph
        database_changed = any(path.name.startswith("index.sqlite") for path in changed)
        if database_changed:
            try:
                graph, warnings = self._rebuild()
            except (sqlite3.Error, ValueError) as error:
                message = str(error)
                if message != self._last_error:
                    print(f"canvas: live graph refresh failed: {error}", file=sys.stderr)
                    self._last_error = message
                return
            self._last_error = ""
            for warning in warnings:
                print(f"canvas: warning: {warning}", file=sys.stderr)
        with self._lock:
            self._signatures = signatures
            self._graph = graph
            self._version += 1


class CanvasServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], state: CanvasState) -> None:
        self.state = state
        self.require_local_host = address[0] in {"127.0.0.1", "::1", "localhost"}
        super().__init__(address, CanvasRequestHandler)


class CanvasRequestHandler(http.server.BaseHTTPRequestHandler):
    server: CanvasServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._route(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        self._route(head_only=True)

    def _route(self, head_only: bool) -> None:
        if self.server.require_local_host and not is_local_host_header(self.headers.get("Host", "")):
            self._send(421, "text/plain; charset=utf-8", b"Misdirected request\n", head_only)
            return
        request_path = urlparse(self.path).path
        if request_path in {"/", "/index.html"}:
            graph, d3_source, version = self.server.state.snapshot()
            payload = render_html(graph, d3_source, live_version=version).encode("utf-8")
            self._send(200, "text/html; charset=utf-8", payload, head_only)
            return
        if request_path == "/api/version":
            _, _, version = self.server.state.snapshot()
            payload = json.dumps({"version": version}, separators=(",", ":")).encode("utf-8")
            self._send(200, "application/json", payload, head_only)
            return
        self._send(404, "text/plain; charset=utf-8", b"Not found\n", head_only)

    def _send(self, status: int, content_type: str, payload: bytes, head_only: bool) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' data:; connect-src 'self'; img-src 'self' data:")
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        if self.command != "GET" or self.path not in {"/api/version"}:
            super().log_message(format, *args)


def default_database(root: Path) -> Path:
    project_index = root / ".qmd" / "index.sqlite"
    if project_index.exists():
        return project_index
    return Path.home() / ".cache" / "qmd" / "index.sqlite"


def available_collections(connection: sqlite3.Connection) -> dict[str, Collection]:
    rows = connection.execute(
        "SELECT name, path, include_by_default FROM store_collections ORDER BY name"
    ).fetchall()
    return {
        row[0]: Collection(row[0], row[1], bool(row[2]))
        for row in rows
    }


def choose_collections(
    available: dict[str, Collection],
    requested: list[str],
    use_all: bool,
    include_private: bool = False,
) -> list[Collection]:
    if requested:
        missing = sorted(set(requested) - available.keys())
        if missing:
            raise ValueError(
                "unknown QMD collection(s): "
                + ", ".join(missing)
                + "; available: "
                + ", ".join(available)
            )
        return [available[name] for name in dict.fromkeys(requested)]
    if use_all:
        return [item for item in available.values() if item.include_by_default]
    if "brain" in available:
        selected = [available["brain"]]
        if include_private and "codex-sessions" in available:
            selected.append(available["codex-sessions"])
        return selected
    defaults = [item for item in available.values() if item.include_by_default]
    if defaults:
        return defaults[:1]
    if available:
        return [next(iter(available.values()))]
    raise ValueError("QMD has no registered collections")


def in_scope(path: str, scope: str) -> bool:
    if scope == "all":
        return True
    normalized = path.lstrip("./")
    if normalized in ROOT_SHARED_FILES:
        return True
    return normalized.split("/", 1)[0] in SHARED_FOLDERS


def is_canvas_content(path: str, is_session: bool = False) -> bool:
    """Exclude generated navigation artifacts without changing QMD coverage."""
    if is_session:
        return True
    normalized = path.lstrip("./")
    top_level = normalized.split("/", 1)[0]
    return (
        top_level in SHARED_FOLDERS | {"local"}
        and Path(normalized).name not in {"index.md", "_index.md", "MEMORY.local.md"}
    )


def collection_root(repository: Path, configured_path: str) -> Path:
    candidate = Path(configured_path).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (repository / candidate).resolve()


def compact_title(value: str, limit: int = 88) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def codex_session_metadata(path: Path) -> tuple[str, str, str, str]:
    """Extract a private session's useful catalog fields without loading its transcript."""
    title = path.stem
    timestamp = ""
    project = ""
    ignored_prefixes = (
        "# AGENTS.md instructions",
        "<environment_context>",
        "<permissions instructions>",
        "<image name=",
    )
    try:
        with path.open(encoding="utf-8") as source:
            for line in source:
                record = json.loads(line)
                payload = record.get("payload", {})
                if record.get("type") == "session_meta":
                    timestamp = str(payload.get("timestamp") or record.get("timestamp") or "")
                    cwd = str(payload.get("cwd") or "")
                    project = Path(cwd).name if cwd else ""
                    continue
                if (
                    record.get("type") != "response_item"
                    or payload.get("type") != "message"
                    or payload.get("role") != "user"
                ):
                    continue
                for content in payload.get("content", []):
                    if content.get("type") != "input_text":
                        continue
                    text = str(content.get("text") or content.get("input_text") or "").strip()
                    if text and not text.startswith(ignored_prefixes):
                        title = compact_title(text)
                        description = f"Codex session{f' · {project}' if project else ''}"
                        return title, description, timestamp, project
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    description = f"Codex session{f' · {project}' if project else ''}"
    return title, description, timestamp, project


def document_nodes(
    connection: sqlite3.Connection,
    repository: Path,
    collections: list[Collection],
    scope: str,
) -> list[DocumentNode]:
    nodes: list[DocumentNode] = []
    for collection in collections:
        rows = connection.execute(
            """
            SELECT path, title, hash
            FROM documents
            WHERE collection = ? AND active = 1
            ORDER BY path
            """,
            (collection.name,),
        ).fetchall()
        base = collection_root(repository, collection.path)
        for path_text, indexed_title, content_hash in rows:
            if not in_scope(path_text, scope):
                continue
            source_path = (base / path_text).resolve()
            metadata: dict[str, object] = {}
            is_session = collection.name == "codex-sessions" or source_path.suffix == ".jsonl"
            if not is_canvas_content(path_text, is_session):
                continue
            session_title = session_description = session_date = session_project = ""
            if source_path.is_file() and is_session and source_path.suffix == ".jsonl":
                session_title, session_description, session_date, session_project = codex_session_metadata(source_path)
            elif source_path.is_file():
                metadata = parse(source_path).metadata
            tags_value = metadata.get("tags", [])
            tags = sorted(str(tag) for tag in tags_value) if isinstance(tags_value, list) else []
            category = "session" if is_session else str(metadata.get("type") or Path(path_text).parts[0] or "document")
            title = session_title or str(metadata.get("title") or indexed_title or Path(path_text).stem)
            description = session_description or str(metadata.get("description") or "")
            date = session_date or str(metadata.get("timestamp") or metadata.get("date") or "")
            project = session_project or str(metadata.get("project") or "")
            nodes.append(
                DocumentNode(
                    id=f"doc:{collection.name}:{path_text}",
                    label=compact_title(title, 32),
                    kind="document",
                    category=category,
                    collection=collection.name,
                    path=path_text,
                    title=title,
                    description=description,
                    tags=tags,
                    url=source_path.as_uri() if source_path.exists() else "",
                    date=date,
                    project=project,
                    is_session=is_session,
                    content_hash=content_hash,
                )
            )
    return nodes


def link_targets(markdown: str) -> list[str]:
    targets = [match.strip() for match in MARKDOWN_LINK.findall(markdown)]
    targets.extend(match.strip() for match in WIKILINK.findall(markdown))
    return targets


def normalize_target(source_path: str, raw_target: str) -> str | None:
    target = raw_target.strip().strip("<>")
    parsed = urlparse(target)
    if parsed.scheme or target.startswith("#"):
        return None
    target = unquote(target.split("#", 1)[0])
    if not target:
        return None
    if not target.lower().endswith(".md"):
        if "[[" not in raw_target and "." in Path(target).name:
            return None
        target += ".md"
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_path), target))


def explicit_edges(nodes: list[DocumentNode], repository: Path, collections: list[Collection]) -> list[Edge]:
    roots = {item.name: collection_root(repository, item.path) for item in collections}
    by_location = {(node.collection, node.path): node.id for node in nodes}
    edges: set[tuple[str, str, str]] = set()
    for node in nodes:
        if node.is_session:
            continue
        path = roots[node.collection] / node.path
        if not path.is_file():
            continue
        for raw_target in link_targets(path.read_text(encoding="utf-8")):
            target_path = normalize_target(node.path, raw_target)
            if not target_path:
                continue
            target_id = by_location.get((node.collection, target_path))
            if target_id and target_id != node.id:
                edges.add((node.id, target_id, "link"))
    return [Edge(*values) for values in sorted(edges)]


def tag_graph(nodes: list[DocumentNode]) -> tuple[list[dict[str, object]], list[Edge]]:
    tag_nodes: list[dict[str, object]] = []
    edges: list[Edge] = []
    for tag in sorted({tag for node in nodes for tag in node.tags}):
        tag_nodes.append(
            {
                "id": f"tag:{tag}",
                "label": tag,
                "kind": "tag",
                "category": "tag",
                "collection": "",
                "path": "",
                "title": tag,
                "description": "Tag",
                "tags": [],
                "url": "",
                "date": "",
                "project": "",
                "is_session": False,
            }
        )
    for node in nodes:
        edges.extend(Edge(node.id, f"tag:{tag}", "tag") for tag in node.tags)
    return tag_nodes, edges


def vector_dimension(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'vectors_vec'"
    ).fetchone()
    if not row or not row[0]:
        raise ValueError("QMD vectors_vec schema is unavailable")
    match = VECTOR_DIMENSION.search(row[0])
    if not match:
        raise ValueError("QMD vector dimension could not be decoded")
    return int(match.group(1))


def document_vectors(
    connection: sqlite3.Connection, nodes: list[DocumentNode]
) -> dict[str, list[float]]:
    wanted_hashes = {node.content_hash for node in nodes}
    if not wanted_hashes:
        return {}
    dimension = vector_dimension(connection)
    rows = connection.execute(
        """
        SELECT cv.hash, cv.seq, vr.chunk_id, vr.chunk_offset
        FROM content_vectors AS cv
        JOIN vectors_vec_rowids AS vr ON vr.id = cv.hash || '_' || cv.seq
        ORDER BY cv.hash, cv.seq
        """
    ).fetchall()
    mappings = [row for row in rows if row[0] in wanted_hashes]
    chunk_ids = sorted({int(row[2]) for row in mappings})
    blobs: dict[int, bytes] = {}
    for chunk_id in chunk_ids:
        row = connection.execute(
            "SELECT vectors FROM vectors_vec_vector_chunks00 WHERE rowid = ?",
            (chunk_id,),
        ).fetchone()
        if row and row[0]:
            blobs[chunk_id] = row[0]

    by_hash: dict[str, list[list[float]]] = defaultdict(list)
    byte_width = dimension * 4
    for content_hash, _, chunk_id, chunk_offset in mappings:
        blob = blobs.get(int(chunk_id))
        offset = int(chunk_offset) * byte_width
        if not blob or offset + byte_width > len(blob):
            raise ValueError("QMD vector chunk layout does not match its row map")
        vector = list(struct.unpack_from(f"<{dimension}f", blob, offset))
        by_hash[content_hash].append(vector)

    node_by_hash = {node.content_hash: node.id for node in nodes}
    result: dict[str, list[float]] = {}
    for content_hash, vectors in by_hash.items():
        averaged = [sum(values) / len(vectors) for values in zip(*vectors)]
        magnitude = math.sqrt(sum(value * value for value in averaged))
        if magnitude:
            result[node_by_hash[content_hash]] = [value / magnitude for value in averaged]
    return result


def semantic_edges(
    vectors: dict[str, list[float]], threshold: float, neighbors: int
) -> list[Edge]:
    scored: dict[str, list[tuple[float, str]]] = defaultdict(list)
    ids = sorted(vectors)
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            score = sum(a * b for a, b in zip(vectors[left], vectors[right]))
            if score >= threshold:
                scored[left].append((score, right))
                scored[right].append((score, left))

    selected: dict[tuple[str, str], float] = {}
    for source, candidates in scored.items():
        for score, target in sorted(candidates, reverse=True)[:neighbors]:
            pair = tuple(sorted((source, target)))
            selected[pair] = max(score, selected.get(pair, -1.0))
    return [
        Edge(source, target, "semantic", round(score, 4))
        for (source, target), score in sorted(selected.items())
    ]


def build_graph(
    repository: Path,
    database: Path,
    requested_collections: list[str],
    use_all_collections: bool,
    scope: str,
    include_semantic: bool,
    semantic_threshold: float,
    semantic_neighbors: int,
) -> tuple[dict[str, object], list[str]]:
    warnings: list[str] = []
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        available = available_collections(connection)
        collections = choose_collections(
            available,
            requested_collections,
            use_all_collections,
            include_private=scope == "all",
        )
        documents = document_nodes(connection, repository, collections, scope)
        tag_nodes, tag_edges = tag_graph(documents)
        edges = explicit_edges(documents, repository, collections) + tag_edges
        if include_semantic:
            try:
                vectors = document_vectors(connection, documents)
                edges.extend(semantic_edges(vectors, semantic_threshold, semantic_neighbors))
            except (sqlite3.Error, ValueError, struct.error) as error:
                warnings.append(f"semantic edges unavailable: {error}")
    finally:
        connection.close()

    public_documents = []
    for node in documents:
        item = asdict(node)
        item.pop("content_hash")
        public_documents.append(item)
    graph_nodes = public_documents + tag_nodes
    graph_edges = [asdict(edge) for edge in edges]
    return (
        {
            "nodes": graph_nodes,
            "links": graph_edges,
            "meta": {
                "collections": [item.name for item in collections],
                "scope": scope,
                "semanticThreshold": semantic_threshold,
                "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        },
        warnings,
    )


def graph_stats(graph: dict[str, object]) -> str:
    nodes = graph["nodes"]
    links = graph["links"]
    assert isinstance(nodes, list) and isinstance(links, list)
    node_kinds = Counter(str(node["kind"]) for node in nodes)
    document_types = Counter(
        str(node["category"]) for node in nodes if node["kind"] == "document"
    )
    edge_kinds = Counter(str(edge["kind"]) for edge in links)
    lines = [
        f"nodes: {len(nodes)} ({', '.join(f'{key}={value}' for key, value in sorted(node_kinds.items()))})",
        f"document types: {', '.join(f'{key}={value}' for key, value in sorted(document_types.items())) or 'none'}",
        f"edges: {len(links)} ({', '.join(f'{key}={value}' for key, value in sorted(edge_kinds.items())) or 'none'})",
    ]
    return "\n".join(lines)


def render_static_svg(graph: dict[str, object]) -> str:
    nodes = graph["nodes"]
    links = graph["links"]
    assert isinstance(nodes, list) and isinstance(links, list)
    if not nodes:
        return '<text class="static-empty" x="600" y="380" text-anchor="middle">No documents in this scope</text>'

    center_x, center_y = 600.0, 380.0
    degree = Counter()
    for edge in links:
        degree[str(edge["source"])] += 1
        degree[str(edge["target"])] += 1
    positions: dict[str, tuple[float, float]] = {}
    ordered = sorted(
        nodes,
        key=lambda item: (
            str(item["kind"]) == "tag",
            -degree[str(item["id"])],
            str(item["label"]),
        ),
    )
    for index, node in enumerate(ordered):
        angle = index * math.pi * (3 - math.sqrt(5)) - math.pi / 2
        radius = 34.0 + math.sqrt(index) * 76.0
        if str(node["kind"]) == "tag":
            radius += 52.0
        positions[str(node["id"])] = (
            center_x + radius * math.cos(angle),
            center_y + radius * 0.72 * math.sin(angle),
        )

    parts = ['<g id="static-graph" aria-label="Static knowledge graph fallback">']
    for edge in links:
        source = positions.get(str(edge["source"]))
        target = positions.get(str(edge["target"]))
        if not source or not target:
            continue
        parts.append(
            '<line class="edge {kind}" x1="{x1:.1f}" y1="{y1:.1f}" '
            'x2="{x2:.1f}" y2="{y2:.1f}" />'.format(
                kind=html.escape(str(edge["kind"])),
                x1=source[0],
                y1=source[1],
                x2=target[0],
                y2=target[1],
            )
        )
    for index, node in enumerate(ordered):
        x, y = positions[str(node["id"])]
        label = html.escape(str(node["label"]))
        kind = str(node["kind"])
        category = str(node.get("category", "document"))
        node_size = min(13.0, 6.5 + math.sqrt(degree[str(node["id"])]) * 1.5)
        if kind == "tag":
            shape = (
                f'<path d="M {x:.1f} {y - node_size:.1f} L {x + node_size:.1f} {y:.1f} '
                f'L {x:.1f} {y + node_size:.1f} L {x - node_size:.1f} {y:.1f} Z" />'
            )
        elif bool(node.get("is_session")):
            shape = (
                f'<rect x="{x - node_size:.1f}" y="{y - node_size:.1f}" '
                f'width="{node_size * 2:.1f}" height="{node_size * 2:.1f}" rx="3" />'
            )
        else:
            shape = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{node_size:.1f}" />'
        label_x = x + node_size + 7 if x >= center_x else x - node_size - 7
        label_anchor = "start" if x >= center_x else "end"
        label_markup = (
            f'<text x="{label_x:.1f}" y="{y + 4:.1f}" '
            f'text-anchor="{label_anchor}">{label}</text>'
            if index < 5 and kind == "document"
            else ""
        )
        parts.append(
            f'<g class="static-node {html.escape(kind)} {html.escape(category)}">{shape}'
            f'{label_markup}</g>'
        )
    parts.append("</g>")
    return "".join(parts)


def render_library(graph: dict[str, object]) -> str:
    nodes = graph["nodes"]
    assert isinstance(nodes, list)
    documents = [node for node in nodes if node["kind"] == "document"]
    collections = Counter(str(node["collection"]) for node in documents)
    sessions = sorted(
        (node for node in documents if node.get("is_session")),
        key=lambda node: (str(node.get("date", "")), str(node["title"])),
        reverse=True,
    )
    labels = {"brain": "Knowledge", "codex-sessions": "Codex sessions"}
    collection_rows = [
        '<button class="library-row is-active" type="button" data-collection="all" aria-pressed="true">'
        f'<span>All documents</span><small>{len(documents)}</small></button>'
    ]
    if len(collections) > 1:
        for name, count in sorted(collections.items()):
            collection_rows.append(
                '<button class="library-row" type="button" '
                f'data-collection="{html.escape(name)}" aria-pressed="false">'
                f'<span>{html.escape(labels.get(name, name))}</span><small>{count}</small></button>'
            )
    category_labels = {
        "pattern": "Patterns",
        "concept": "Concepts",
        "decision": "Decisions",
        "lesson": "Lessons",
        "snippet": "Snippets",
        "source": "Sources",
        "infra": "Infrastructure",
        "local": "Local knowledge",
        "note": "Notes",
    }
    category_counts = Counter(
        str(node.get("category", "source"))
        for node in documents
        if not node.get("is_session")
    )
    category_rows = [
        '<button class="library-row" type="button" '
        f'data-category="{html.escape(category)}" aria-pressed="false">'
        f'<span><i class="category-dot {html.escape(category)}"></i>'
        f'{html.escape(category_labels.get(category, category.title()))}</span>'
        f'<small>{count}</small></button>'
        for category, count in sorted(
            category_counts.items(),
            key=lambda item: (list(category_labels).index(item[0]) if item[0] in category_labels else 99, item[0]),
        )
    ]
    if sessions:
        session_rows = []
        for node in sessions:
            date = str(node.get("date", ""))
            date_label = date[:10] + (f" · {date[11:16]}" if len(date) >= 16 else "")
            project = str(node.get("project") or "Codex")
            session_rows.append(
                '<button class="session-row" type="button" '
                f'data-node-id="{html.escape(str(node["id"]))}" '
                f'aria-label="{html.escape(str(node["title"]))}">'
                f'<span>{html.escape(str(node["title"]))}</span>'
                f'<small>{html.escape(project)}{f" · {html.escape(date_label)}" if date_label else ""}</small>'
                '</button>'
            )
        sessions_html = "".join(session_rows)
    else:
        sessions_html = (
            '<p class="library-empty"><strong>Session history is private.</strong>'
            '<span>Use an all-scope canvas when you want to browse recent work here.</span></p>'
        )
    return (
        '<nav class="library" id="library" aria-label="Knowledge library">'
        '<div class="panel-heading"><div><h2>Explore</h2><p>Browse knowledge and recent work</p></div></div>'
        '<div class="library-scroll">'
        '<section class="library-section"><h3>Library</h3>'
        + "".join(collection_rows)
        + '</section><section class="library-section"><h3>Knowledge types</h3>'
        + "".join(category_rows)
        + '</section><section class="library-section sessions"><h3>Sessions</h3>'
        + sessions_html
        + '</section></div></nav>'
    )


def render_html(
    graph: dict[str, object],
    d3_source: str,
    live_version: int | None = None,
) -> str:
    static_graph = render_static_svg(graph)
    library = render_library(graph)
    nodes = graph["nodes"]
    links = graph["links"]
    meta = graph["meta"]
    assert isinstance(nodes, list) and isinstance(links, list) and isinstance(meta, dict)
    render_meta = dict(meta)
    if live_version is not None:
        render_meta["liveReload"] = {"version": live_version, "url": "/api/version"}
    render_graph = {**graph, "meta": render_meta}
    data = json.dumps(render_graph, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    document_count = sum(node["kind"] == "document" for node in nodes)
    tag_count = sum(node["kind"] == "tag" for node in nodes)
    scope_label = f'{meta.get("scope", "shared")} · {", ".join(meta.get("collections", []))}'
    initial_status = f"{document_count} documents · {tag_count} tags · {len(links)} visible edges"
    # Keep the UI maintainable in dedicated source files; Python only injects
    # the graph data and inlined runtime assets into those templates.
    template_path = Path(__file__).with_name("canvas.html")
    script_path = Path(__file__).with_name("canvas.js")
    logo_path = Path(__file__).parents[1] / "docs" / "assets" / "brain-logo.svg"
    template = template_path.read_text(encoding="utf-8")
    script = script_path.read_text(encoding="utf-8").replace("__GRAPH_DATA__", data)
    favicon = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    return (
        template.replace("__LIBRARY__", library)
        .replace("__STATIC_GRAPH__", static_graph)
        .replace("__D3_SOURCE__", d3_source)
        .replace("__CANVAS_JS__", script)
        .replace("__FAVICON__", favicon)
        .replace("__SCOPE_LABEL__", html.escape(scope_label))
        .replace("__INITIAL_STATUS__", html.escape(initial_status))
    )



def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--collection", action="append", default=[], help="QMD collection to graph; repeatable")
    selection.add_argument("--all-collections", action="store_true", help="Graph every include-by-default collection")
    parser.add_argument("--scope", choices=("shared", "all"), default="shared", help="Default excludes private local knowledge")
    parser.add_argument("--database", type=Path, default=default_database(repository), help="QMD SQLite index")
    parser.add_argument("--output", type=Path, help="Export one offline HTML file instead of starting the live server")
    parser.add_argument("--no-semantic", action="store_true", help="Skip QMD vector similarity edges")
    parser.add_argument("--semantic-threshold", type=float, default=0.55)
    parser.add_argument("--semantic-neighbors", type=int, default=2)
    parser.add_argument("--host", default="127.0.0.1", help="Live server bind address (default: loopback only)")
    parser.add_argument("--port", type=int, default=8765, help="Live server port (default: 8765; use 0 for any free port)")
    parser.add_argument("--poll-interval", "--watch", dest="poll_interval", type=float, default=0.75, metavar="SECONDS", help="UI/QMD change detection interval (default: 0.75)")
    parser.add_argument("--no-open", action="store_true", help="Do not launch the live URL or exported file")
    parser.add_argument("--dry-run", action="store_true", help="Print graph counts without serving or exporting")
    args = parser.parse_args()

    if not 0 <= args.semantic_threshold <= 1:
        parser.error("--semantic-threshold must be between 0 and 1")
    if args.semantic_neighbors < 1:
        parser.error("--semantic-neighbors must be at least 1")
    if args.poll_interval < 0.25:
        parser.error("--poll-interval must be at least 0.25 seconds")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    database = args.database.expanduser().resolve()
    if not database.is_file():
        parser.error(f"QMD index not found: {database}; run scripts/qmd.sh update")

    try:
        graph, warnings = build_graph(
            repository,
            database,
            args.collection,
            args.all_collections,
            args.scope,
            not args.no_semantic,
            args.semantic_threshold,
            args.semantic_neighbors,
        )
    except (sqlite3.Error, ValueError) as error:
        print(f"canvas: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"canvas: warning: {warning}", file=sys.stderr)
    print(graph_stats(graph))
    if args.dry_run:
        return 0

    d3_path = repository / "bin" / "node_modules" / "d3" / "dist" / "d3.min.js"
    d3_license_path = repository / "bin" / "node_modules" / "d3" / "LICENSE"
    if not d3_path.is_file():
        print("canvas: D3 is not installed; run `npm install --prefix bin`", file=sys.stderr)
        return 1
    if not d3_license_path.is_file():
        print("canvas: D3 license is missing; reinstall with `npm install --prefix bin`", file=sys.stderr)
        return 1
    d3_license = d3_license_path.read_text(encoding="utf-8").strip()
    d3_source = f"/*\nD3.js license\n\n{d3_license}\n*/\n{d3_path.read_text(encoding='utf-8')}"
    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_output = output.with_suffix(f"{output.suffix}.tmp")
        temporary_output.write_text(render_html(graph, d3_source), encoding="utf-8")
        temporary_output.replace(output)
        print(f"exported {output}")
        if not args.no_open:
            webbrowser.open(output.as_uri())
        return 0

    def rebuild() -> tuple[dict[str, object], list[str]]:
        return build_graph(
            repository,
            database,
            args.collection,
            args.all_collections,
            args.scope,
            not args.no_semantic,
            args.semantic_threshold,
            args.semantic_neighbors,
        )

    database_sidecars = [Path(f"{database}{suffix}") for suffix in ("-wal", "-shm")]
    state = CanvasState(
        graph,
        d3_source,
        [Path(__file__).with_name("canvas.html"), Path(__file__).with_name("canvas.js"), database, *database_sidecars],
        rebuild,
    )
    server = CanvasServer((args.host, args.port), state)
    bound_host, bound_port = server.server_address[:2]
    browser_host = "127.0.0.1" if bound_host in {"0.0.0.0", "::"} else bound_host
    url = f"http://{browser_host}:{bound_port}/"
    stop_watcher = threading.Event()

    def watch() -> None:
        while not stop_watcher.wait(args.poll_interval):
            state.refresh_if_changed()

    watcher = threading.Thread(target=watch, name="brain-canvas-watch", daemon=True)
    watcher.start()
    print(f"serving live canvas at {url}")
    print("watching UI source and QMD index changes (Ctrl-C to stop)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\ncanvas: stopped")
    finally:
        stop_watcher.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
