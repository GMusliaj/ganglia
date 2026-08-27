#!/usr/bin/env python3
"""Render QMD-indexed Brain Markdown as an offline force-directed graph.

    bin/canvas.py                         # build the shared graph and open it
    bin/canvas.py --collection brain      # select a collection (repeatable)
    bin/canvas.py --all-collections       # every include-by-default collection
    bin/canvas.py --scope all             # explicitly include local/operating docs
    bin/canvas.py --no-open               # build without launching a browser
    bin/canvas.py --dry-run               # report counts without writing

The default view contains the shared knowledge layer. Nodes are documents plus
small tag nodes. Independently togglable edges represent Markdown links and
wikilinks, document-to-tag membership, and semantic similarity from QMD's own
vector index.

The generated HTML is a disposable local artifact. D3 is inlined so the output
works offline; Markdown remains canonical; and semantic decoding degrades with
one warning when QMD's internal, undocumented vector storage changes shape.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import posixpath
import re
import sqlite3
import struct
import sys
import webbrowser
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
                    label=title,
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
        f'<span>All knowledge</span><small>{len(documents)}</small></button>'
    ]
    for name, count in sorted(collections.items()):
        collection_rows.append(
            '<button class="library-row" type="button" '
            f'data-collection="{html.escape(name)}" aria-pressed="false">'
            f'<span>{html.escape(labels.get(name, name))}</span><small>{count}</small></button>'
        )
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
            '<p class="library-empty">Private sessions are available when the canvas is built with '
            '<code>--scope all</code>.</p>'
        )
    return (
        '<nav class="library" id="library" aria-label="Knowledge library">'
        '<div class="panel-heading"><div><h2>Library</h2><p>Collections and recent work</p></div></div>'
        '<div class="library-scroll">'
        '<section class="library-section"><h3>Collections</h3>'
        + "".join(collection_rows)
        + '</section><section class="library-section sessions"><h3>Sessions</h3>'
        + sessions_html
        + '</section></div></nav>'
    )


def render_html(graph: dict[str, object], d3_source: str) -> str:
    data = json.dumps(graph, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    static_graph = render_static_svg(graph)
    library = render_library(graph)
    nodes = graph["nodes"]
    links = graph["links"]
    meta = graph["meta"]
    assert isinstance(nodes, list) and isinstance(links, list) and isinstance(meta, dict)
    document_count = sum(node["kind"] == "document" for node in nodes)
    tag_count = sum(node["kind"] == "tag" for node in nodes)
    scope_label = f'{meta.get("scope", "shared")} · {", ".join(meta.get("collections", []))}'
    initial_status = f"{document_count} documents · {tag_count} tags · {len(links)} visible edges"
    template = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brain canvas</title>
<style>
:root{color-scheme:light dark;--background:#f5f6f7;--surface:#fff;--surface-raised:#fff;--foreground:#182026;--muted-foreground:#5f6b73;--border:#d5dbde;--control-hover:#edf1f2;--primary:#0f766e;--primary-soft:#dcefeb;--pattern:#0f766e;--concept:#2563a6;--decision:#a16207;--session:#7651a8;--source:#64748b;--tag:#687783;--semantic:#9a6b22;--shadow:0 14px 36px rgba(28,39,45,.14)}
@media(prefers-color-scheme:dark){:root{--background:#101416;--surface:#151a1d;--surface-raised:#1b2124;--foreground:#edf1f2;--muted-foreground:#a9b3b8;--border:#3a454b;--control-hover:#222a2e;--primary:#5fc4b7;--primary-soft:#173d39;--pattern:#5fc4b7;--concept:#78aee8;--decision:#d2a65c;--session:#b79add;--source:#a1adb3;--tag:#a1adb3;--semantic:#d2a65c;--shadow:0 18px 44px rgba(0,0,0,.34)}}
*{box-sizing:border-box}[hidden]{display:none!important}html,body{min-width:320px;min-height:100%;overflow:hidden}body{margin:0;background:var(--background);color:var(--foreground);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input,summary{font:inherit}button,input{color:inherit}button{cursor:pointer}.shell{height:100dvh;display:grid;grid-template-rows:auto minmax(0,1fr)}
.topbar{min-height:64px;display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid var(--border);background:var(--surface);position:relative;z-index:40}.identity{display:flex;align-items:center;gap:10px;min-width:max-content;margin-right:auto}.identity-mark{width:26px;height:26px;color:var(--primary)}.identity h1{margin:0;font-size:15px;line-height:1.2;font-weight:500}.identity p{margin:2px 0 0;color:var(--muted-foreground);font-size:12px}.toolbar{display:flex;align-items:center;justify-content:flex-end;gap:8px}.search-wrap{position:relative}.search-icon{position:absolute;left:12px;top:50%;width:16px;height:16px;transform:translateY(-50%);color:var(--muted-foreground);pointer-events:none}.search{width:min(28vw,320px);min-width:220px;height:40px;padding:0 34px 0 38px;border:1px solid var(--border);border-radius:8px;background:var(--surface);outline:none}.search::placeholder{color:var(--muted-foreground)}.search::-webkit-search-cancel-button{display:none}.search-clear{position:absolute;right:4px;top:4px;width:32px;height:32px;border:0;border-radius:6px;background:transparent;color:var(--muted-foreground);font-size:18px}.search-clear:hover{background:var(--control-hover);color:var(--foreground)}
.button,.connection-menu summary,.open-link{min-height:40px;display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:0 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--foreground);text-decoration:none;font-weight:500;transition:background-color 160ms ease,border-color 160ms ease}.button:hover,.connection-menu summary:hover,.open-link:hover{background:var(--control-hover)}.button svg,.connection-menu summary svg,.open-link svg{width:16px;height:16px;flex:none}.button.icon-only{width:40px;padding:0}.button:focus-visible,.search:focus-visible,.search-clear:focus-visible,.connection-menu summary:focus-visible,.open-link:focus-visible,.library-row:focus-visible,.session-row:focus-visible,.relation-row:focus-visible{outline:3px solid var(--primary);outline-offset:2px}.mobile-details{display:none}
.connection-menu{position:relative}.connection-menu summary{list-style:none;cursor:pointer;user-select:none}.connection-menu summary::-webkit-details-marker{display:none}.connection-menu[open] summary{background:var(--control-hover);border-color:var(--primary)}.menu-panel{position:absolute;right:0;top:48px;width:246px;padding:8px;border:1px solid var(--border);border-radius:10px;background:var(--surface-raised);box-shadow:var(--shadow);z-index:50}.layer-control{min-height:44px;display:grid;grid-template-columns:20px 1fr auto;align-items:center;gap:10px;padding:7px 8px;border-radius:7px;cursor:pointer}.layer-control:hover{background:var(--control-hover)}.layer-control input{width:16px;height:16px;margin:0;accent-color:var(--primary)}.layer-control span{display:block}.layer-control small{display:block;color:var(--muted-foreground);font-size:11px}.edge-sample{width:20px;height:0;border-top:2px solid var(--tag)}.edge-sample.tag{border-top-style:dotted;border-top-color:var(--primary)}.edge-sample.semantic{border-top-style:dashed;border-top-color:var(--semantic)}
.workspace{position:relative;min-height:0;display:grid;grid-template-columns:276px minmax(0,1fr) 320px;transition:grid-template-columns 220ms cubic-bezier(.2,.8,.2,1)}.workspace.library-collapsed{grid-template-columns:0 minmax(0,1fr) 320px}.library,.inspector-panel{min-width:0;background:var(--surface);overflow:hidden}.library{border-right:1px solid var(--border);transition:opacity 160ms ease,transform 220ms cubic-bezier(.2,.8,.2,1)}.workspace.library-collapsed .library{opacity:0;transform:translateX(-20px);pointer-events:none}.inspector-panel{border-left:1px solid var(--border);display:flex;flex-direction:column}.panel-heading{min-height:65px;display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid var(--border)}.panel-heading h2{margin:0;font-size:14px;font-weight:500}.panel-heading p{margin:2px 0 0;color:var(--muted-foreground);font-size:12px}.library-scroll,.inspector-scroll{overflow-y:auto;overscroll-behavior:contain}.library-scroll{height:calc(100% - 65px);padding:14px 10px 28px}.library-section{margin-bottom:22px}.library-section h3,.inspector-section h3{margin:0 8px 8px;color:var(--muted-foreground);font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.08em}.library-row,.session-row,.relation-row{width:100%;border:0;background:transparent;color:var(--foreground);text-align:left;border-radius:7px;transition:background-color 140ms ease,color 140ms ease}.library-row{min-height:38px;display:flex;align-items:center;justify-content:space-between;padding:7px 9px}.library-row small{color:var(--muted-foreground);font-variant-numeric:tabular-nums}.library-row:hover,.session-row:hover,.relation-row:hover{background:var(--control-hover)}.library-row.is-active{background:var(--primary-soft);color:var(--foreground)}.session-row{display:block;padding:8px 9px;margin-bottom:2px}.session-row span{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.session-row small{display:block;margin-top:2px;color:var(--muted-foreground);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.session-row.search-hidden{display:none}.library-empty{margin:8px;padding:10px;color:var(--muted-foreground);font-size:12px;background:var(--control-hover);border-radius:7px}.library-empty code{color:var(--foreground)}
.graph-wrap{position:relative;min-width:0;overflow:hidden;background:var(--background);isolation:isolate}.graph-wrap::before{content:"";position:absolute;inset:0;pointer-events:none;background-image:radial-gradient(var(--border) .7px,transparent .7px);background-size:22px 22px;opacity:.32}#graph{position:relative;z-index:1;display:block;width:100%;height:100%;min-height:520px;touch-action:none}.edge{stroke:var(--tag);stroke-width:1;opacity:.34}.edge.tag{stroke:var(--primary);stroke-dasharray:2 5;opacity:.3}.edge.semantic{stroke:var(--semantic);stroke-dasharray:8 7;opacity:.27}.node{cursor:grab;outline:none;transition:opacity 150ms ease}.node:active{cursor:grabbing}.node .hit-area{fill:transparent;stroke:none;pointer-events:all}.node path{stroke:var(--background);stroke-width:2;transition:stroke-width 150ms ease,filter 150ms ease}.node text,.static-node text{fill:var(--foreground);font-size:12px;font-weight:500;paint-order:stroke;stroke:var(--background);stroke-width:5px;stroke-linejoin:round;pointer-events:none}.node text{opacity:0;transition:opacity 140ms ease}.node.prominent text,.node:hover text,.node:focus text,.node.selected text,.node.match text{opacity:1}.node.dimmed{opacity:.1}.node.filtered{display:none}.node.match path{stroke:var(--foreground);stroke-width:3}.node.selected path,.node:focus-visible path{stroke:var(--foreground);stroke-width:4;filter:drop-shadow(0 3px 5px rgba(0,0,0,.16))}.static-node circle,.static-node rect,.static-node path{stroke:var(--background);stroke-width:2}.static-empty{fill:var(--muted-foreground)}.status{position:absolute;z-index:5;left:18px;bottom:16px;display:flex;align-items:center;gap:8px;color:var(--muted-foreground);font-size:12px;pointer-events:none}.status::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--primary)}
.inspector-scroll{padding:18px;height:100%}.inspector-empty{color:var(--muted-foreground);padding:4px 0 18px}.detail-content{opacity:0;transform:translateY(6px);visibility:hidden;height:0;overflow:hidden;transition:opacity 180ms ease,transform 220ms cubic-bezier(.2,.8,.2,1)}.detail-content.is-visible{opacity:1;transform:none;visibility:visible;height:auto;overflow:visible}.detail-kind{margin:0 0 6px;color:var(--muted-foreground);font-size:11px;text-transform:uppercase;letter-spacing:.08em}.detail-content h2{margin:0;font-size:18px;line-height:1.35;font-weight:500;overflow-wrap:anywhere}.detail-description{margin:10px 0;color:var(--muted-foreground)}.detail-path{margin:8px 0;color:var(--muted-foreground);font:11px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}.detail-meta{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}.badge{padding:3px 7px;border-radius:999px;background:var(--control-hover);color:var(--muted-foreground);font-size:11px}.open-link{margin-top:2px}.inspector-section{padding-top:18px;margin-top:18px;border-top:1px solid var(--border)}.inspector-section h3{margin-left:0}.relation-group{margin-top:12px}.relation-group h4{margin:0 0 5px;color:var(--muted-foreground);font-size:12px;font-weight:500}.relation-row{display:grid;grid-template-columns:8px minmax(0,1fr) auto;align-items:center;gap:8px;min-height:36px;padding:6px 7px}.relation-dot,.legend-mark{display:inline-block;background:var(--source)}.relation-row span:nth-child(2){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.relation-row small{color:var(--muted-foreground);font-size:10px}.relations-empty{color:var(--muted-foreground);font-size:12px}.legend-list{display:grid;gap:9px}.legend-item{display:grid;grid-template-columns:18px 1fr;align-items:center;gap:9px;color:var(--muted-foreground);font-size:12px}.legend-mark{width:10px;height:10px;border-radius:50%;justify-self:center}.legend-mark.session{border-radius:3px}.legend-mark.tag{transform:rotate(45deg);border-radius:1px}.legend-line{width:18px;height:0;border-top:2px solid var(--tag)}.legend-line.tag-edge{border-top-style:dotted;border-top-color:var(--primary)}.legend-line.semantic{border-top-style:dashed;border-top-color:var(--semantic)}.pattern{background:var(--pattern)}.concept{background:var(--concept)}.decision{background:var(--decision)}.session{background:var(--session)}.source{background:var(--source)}.tag{background:var(--tag)}.static-node.pattern circle{fill:var(--pattern)}.static-node.concept circle{fill:var(--concept)}.static-node.decision circle{fill:var(--decision)}.static-node.session rect{fill:var(--session)}.static-node.tag path{fill:var(--tag)}.sidebar-scrim{display:none}.sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
@media(max-width:1120px){.workspace{grid-template-columns:236px minmax(0,1fr) 286px}.workspace.library-collapsed{grid-template-columns:0 minmax(0,1fr) 286px}.identity p{display:none}.search{width:min(28vw,270px)}}
@media(max-width:820px){html,body{overflow:auto}.shell{min-height:100dvh;height:auto;grid-template-rows:auto minmax(600px,1fr)}.topbar{align-items:flex-start;flex-wrap:wrap;padding:10px 12px}.identity{margin-right:auto}.toolbar{order:2;width:100%;justify-content:stretch}.search-wrap{flex:1;min-width:0}.search{width:100%;min-width:0;font-size:16px}.connection-menu summary .button-label{display:none}.connection-menu summary{width:40px;padding:0}.menu-panel{right:-48px}.mobile-details{display:inline-flex}.workspace,.workspace.library-collapsed{min-height:600px;grid-template-columns:1fr}.library,.inspector-panel{position:absolute;top:0;bottom:0;width:min(88vw,320px);z-index:30;box-shadow:var(--shadow);transition:transform 220ms cubic-bezier(.2,.8,.2,1),opacity 180ms ease}.library{left:0;transform:translateX(-105%);opacity:0}.inspector-panel{right:0;transform:translateX(105%);opacity:0}.workspace.library-open .library,.workspace.inspector-open .inspector-panel{transform:none;opacity:1}.workspace.library-collapsed .library{transform:translateX(-105%)}.sidebar-scrim{position:absolute;inset:0;z-index:25;border:0;background:rgba(8,12,14,.34)}.workspace.library-open .sidebar-scrim,.workspace.inspector-open .sidebar-scrim{display:block}.node.prominent text{opacity:0}.node.selected text,.node:focus text,.node.match text{opacity:1}.status{left:12px;bottom:12px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition-duration:.01ms!important;animation-duration:.01ms!important}}
</style>
</head>
<body>
<main class="shell">
  <header class="topbar">
    <button class="button icon-only" id="library-toggle" type="button" aria-label="Toggle library" aria-controls="library" aria-expanded="true"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16M4 12h16M4 19h16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg></button>
    <div class="identity"><svg class="identity-mark" viewBox="0 0 28 28" aria-hidden="true"><circle cx="7" cy="14" r="3" fill="currentColor"/><circle cx="21" cy="7" r="3" fill="currentColor"/><circle cx="21" cy="21" r="3" fill="currentColor"/><path d="M9.5 12.8 18.3 8.2M9.5 15.2l8.8 4.6" fill="none" stroke="currentColor" stroke-width="1.5"/></svg><div><h1>Knowledge map</h1><p id="scope-label">__SCOPE_LABEL__</p></div></div>
    <div class="toolbar" aria-label="Canvas controls">
      <div class="search-wrap"><label class="sr-only" for="search">Search titles, paths, tags, and sessions</label><svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m16 16 4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><input class="search" id="search" type="search" placeholder="Search knowledge and sessions" autocomplete="off"><button class="search-clear" id="search-clear" type="button" aria-label="Clear search" hidden>&times;</button></div>
      <details class="connection-menu" id="connection-menu"><summary><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M6 14v6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg><span class="button-label">Connections</span></summary><div class="menu-panel" aria-label="Visible connection types"><label class="layer-control"><input id="layer-link" type="checkbox" checked><span>Markdown links<small>Explicit references</small></span><i class="edge-sample"></i></label><label class="layer-control"><input id="layer-tag" type="checkbox" checked><span>Tag membership<small>Shared taxonomy</small></span><i class="edge-sample tag"></i></label><label class="layer-control"><input id="layer-semantic" type="checkbox" checked><span>Semantic similarity<small>Best-effort QMD layer</small></span><i class="edge-sample semantic"></i></label></div></details>
      <button class="button icon-only" id="fit" type="button" aria-label="Fit graph to view"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
      <button class="button icon-only mobile-details" id="details-toggle" type="button" aria-label="Show node details" aria-controls="inspector" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M12 11v6M12 7.5v.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>
    </div>
  </header>
  <div class="workspace" id="workspace">
    __LIBRARY__
    <section class="graph-wrap" aria-label="Interactive Brain knowledge graph"><svg id="graph" viewBox="0 0 1200 760" role="img" aria-labelledby="graph-title graph-desc"><title id="graph-title">Brain knowledge graph</title><desc id="graph-desc">Circles are durable knowledge, rounded squares are Codex sessions, and diamonds are tags. Select a node to inspect linked knowledge.</desc>__STATIC_GRAPH__</svg><div class="status" id="counts" role="status" aria-live="polite">__INITIAL_STATUS__</div></section>
    <aside class="inspector-panel" id="inspector" aria-label="Node details"><div class="panel-heading"><div><h2>Inspector</h2><p>Selection and relationships</p></div></div><div class="inspector-scroll"><p class="inspector-empty" id="inspector-empty">Select a node to inspect its linked patterns, concepts, decisions, tags, and sessions.</p><div class="detail-content" id="detail-content" aria-live="polite"><p class="detail-kind" id="detail-kind"></p><h2 id="detail-title"></h2><p class="detail-description" id="detail-description"></p><p class="detail-path" id="detail-path"></p><div class="detail-meta" id="detail-tags"></div><a class="open-link" id="detail-open" hidden><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 5h5v5M19 5l-8 8M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg><span>Open source</span></a><section class="inspector-section"><h3>Linked knowledge</h3><div id="relations"></div></section></div><section class="inspector-section"><h3>Map key</h3><div class="legend-list"><div class="legend-item"><i class="legend-mark pattern"></i><span>Pattern</span></div><div class="legend-item"><i class="legend-mark concept"></i><span>Concept</span></div><div class="legend-item"><i class="legend-mark decision"></i><span>Decision</span></div><div class="legend-item"><i class="legend-mark session"></i><span>Codex session</span></div><div class="legend-item"><i class="legend-mark tag"></i><span>Tag</span></div><div class="legend-item"><i class="legend-line"></i><span>Markdown link</span></div><div class="legend-item"><i class="legend-line tag-edge"></i><span>Tag membership</span></div><div class="legend-item"><i class="legend-line semantic"></i><span>Semantic similarity</span></div></div></section></div></aside>
    <button class="sidebar-scrim" id="sidebar-scrim" type="button" aria-label="Close side panel"></button>
  </div>
</main>
<script>__D3_SOURCE__</script>
<script>
const graph=__GRAPH_DATA__,workspace=document.getElementById("workspace");
const svg=d3.select("#graph"),element=svg.node(),nodes=graph.nodes.map(d=>({...d})),allLinks=graph.links.map(d=>({...d})),nodeById=new Map(nodes.map(d=>[d.id,d]));
svg.select("#static-graph").remove();
const wrap=element.parentElement,zoomRoot=svg.append("g"),linkLayer=zoomRoot.append("g"),nodeLayer=zoomRoot.append("g"),motionReduced=matchMedia("(prefers-reduced-motion: reduce)");
const endpointId=value=>typeof value==="object"?value.id:value;
const degree=new Map(nodes.map(d=>[d.id,0]));allLinks.forEach(d=>{degree.set(endpointId(d.source),(degree.get(endpointId(d.source))||0)+1);degree.set(endpointId(d.target),(degree.get(endpointId(d.target))||0)+1)});
const prominentList=[...nodes].filter(d=>d.kind==="document"&&!d.is_session).sort((a,b)=>(degree.get(b.id)||0)-(degree.get(a.id)||0)).slice(0,5),prominent=new Set(prominentList.map(d=>d.id)),labelLeft=new Set(prominentList.filter((_,i)=>i%2).map(d=>d.id));
const colorMap={pattern:"var(--pattern)",concept:"var(--concept)",decision:"var(--decision)",session:"var(--session)",source:"var(--source)",tag:"var(--tag)"};
let visibleNodes=[...nodes],visibleIds=new Set(nodes.map(d=>d.id)),activeLinks=[],activeCollection="all",selectedNode=null,resizeFrame=0,initialFitPending=true;
function compactGraph(){return wrap.clientWidth<600}function chargeStrength(d){return compactGraph()?(d.kind==="tag"?-48:-88):(d.kind==="tag"?-72:-155)}function collisionRadius(d){return compactGraph()?(d.kind==="tag"?20:27):(d.kind==="tag"?30:40)}function linkDistance(d){return compactGraph()?(d.kind==="tag"?62:d.kind==="semantic"?92:78):(d.kind==="tag"?96:d.kind==="semantic"?142:116)}
const simulation=d3.forceSimulation(nodes).randomSource(d3.randomLcg(.417)).alphaDecay(.038).velocityDecay(.42).force("charge",d3.forceManyBody().strength(chargeStrength)).force("center",d3.forceCenter()).force("x",d3.forceX().strength(.035)).force("y",d3.forceY().strength(.035)).force("collision",d3.forceCollide().radius(collisionRadius));
let linkSelection,nodeSelection;
function fillFor(d){return colorMap[d.is_session?"session":d.category]||colorMap.source}function symbol(d){const base=d.kind==="tag"?90:170,weight=Math.min(180,(degree.get(d.id)||0)*18),type=d.kind==="tag"?d3.symbolDiamond:d.is_session?d3.symbolSquare:d3.symbolCircle;return d3.symbol().type(type).size(base+weight)()}
nodeSelection=nodeLayer.selectAll("g").data(nodes,d=>d.id).join("g").attr("class",d=>`node ${d.kind} ${d.category} ${prominent.has(d.id)?"prominent":""}`).attr("role","button").attr("tabindex",0).attr("aria-label",d=>`${d.title}, ${d.category}`).call(d3.drag().on("start",dragStart).on("drag",dragged).on("end",dragEnd));
nodeSelection.append("circle").attr("class","hit-area").attr("r",22);nodeSelection.append("path").attr("d",symbol).attr("fill",fillFor);nodeSelection.append("text").attr("x",d=>labelLeft.has(d.id)?-14:14).attr("y",4).attr("text-anchor",d=>labelLeft.has(d.id)?"end":"start").text(d=>d.label);
nodeSelection.on("click",(_,d)=>selectNode(d,true)).on("focus",(_,d)=>selectNode(d,false)).on("keydown",(event,d)=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();selectNode(d,true)}}).on("dblclick",(_,d)=>{if(d.url)location.href=d.url});
simulation.on("tick",()=>{linkSelection?.attr("x1",d=>d.source.x).attr("y1",d=>d.source.y).attr("x2",d=>d.target.x).attr("y2",d=>d.target.y);nodeSelection.attr("transform",d=>`translate(${d.x},${d.y})`)}).on("end",()=>{if(initialFitPending&&!selectedNode){initialFitPending=false;fit()}});
const zoom=d3.zoom().scaleExtent([.18,4]).on("zoom",event=>zoomRoot.attr("transform",event.transform));svg.call(zoom);
function size(){const width=wrap.clientWidth,height=element.clientHeight;svg.attr("viewBox",[0,0,width,height]);simulation.force("center",d3.forceCenter(width/2,height/2));simulation.force("x").x(width/2);simulation.force("y").y(height/2);simulation.force("charge").strength(chargeStrength);simulation.force("collision").radius(collisionRadius);const force=simulation.force("link");if(force)force.distance(linkDistance)}
function enabled(kind){return document.getElementById(`layer-${kind}`).checked}function edgeVisible(d){return visibleIds.has(endpointId(d.source))&&visibleIds.has(endpointId(d.target))}
function updateLinks(){activeLinks=allLinks.filter(d=>enabled(d.kind)&&edgeVisible(d));linkSelection=linkLayer.selectAll("line").data(activeLinks,d=>`${endpointId(d.source)}|${endpointId(d.target)}|${d.kind}`).join("line").attr("class",d=>`edge ${d.kind}`).attr("aria-label",d=>d.kind==="semantic"?`Semantic similarity ${Math.round((d.score||0)*100)} percent`:d.kind);simulation.force("link",d3.forceLink(activeLinks).id(d=>d.id).distance(linkDistance).strength(d=>d.kind==="semantic"?.1:.24));simulation.alpha(.72).restart();updateCounts()}
function setCollection(name,shouldFit=true){activeCollection=name;const docs=nodes.filter(d=>d.kind==="document"&&(name==="all"||d.collection===name)),ids=new Set(docs.map(d=>d.id));allLinks.filter(d=>d.kind==="tag"&&(ids.has(endpointId(d.source))||ids.has(endpointId(d.target)))).forEach(d=>{ids.add(endpointId(d.source));ids.add(endpointId(d.target))});visibleNodes=nodes.filter(d=>ids.has(d.id));visibleIds=new Set(visibleNodes.map(d=>d.id));nodeSelection.classed("filtered",d=>!visibleIds.has(d.id));simulation.nodes(visibleNodes);document.querySelectorAll("[data-collection]").forEach(button=>{const active=button.dataset.collection===name;button.classList.toggle("is-active",active);button.setAttribute("aria-pressed",String(active))});if(selectedNode&&!visibleIds.has(selectedNode.id))clearSelection();updateLinks();if(shouldFit)setTimeout(fit,360)}
function fit(){const positioned=visibleNodes.filter(d=>Number.isFinite(d.x)&&Number.isFinite(d.y)),width=wrap.clientWidth,height=element.clientHeight;if(!positioned.length)return;const xs=positioned.map(d=>d.x),ys=positioned.map(d=>d.y),padding=compactGraph()?24:44,minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys),boundsWidth=Math.max(1,maxX-minX+padding*2),boundsHeight=Math.max(1,maxY-minY+padding*2),maxScale=compactGraph()?2.6:1.9,scale=Math.min(maxScale,.84/Math.max(boundsWidth/width,boundsHeight/height)),transform=d3.zoomIdentity.translate(width/2,height/2).scale(scale).translate(-(minX+maxX)/2,-(minY+maxY)/2);if(motionReduced.matches)svg.call(zoom.transform,transform);else svg.transition().duration(320).ease(d3.easeCubicOut).call(zoom.transform,transform)}
function focusNode(d){if(!Number.isFinite(d.x)||!Number.isFinite(d.y))return;const current=d3.zoomTransform(element),scale=Math.max(1.15,Math.min(2,current.k));const transform=d3.zoomIdentity.translate(wrap.clientWidth/2,element.clientHeight/2).scale(scale).translate(-d.x,-d.y);if(motionReduced.matches)svg.call(zoom.transform,transform);else svg.transition().duration(300).ease(d3.easeCubicOut).call(zoom.transform,transform)}
function relationNodes(d){const related=new Map(),precedence={link:3,tag:2,semantic:1};for(const link of allLinks){const source=endpointId(link.source),target=endpointId(link.target);if(source!==d.id&&target!==d.id)continue;const other=nodeById.get(source===d.id?target:source);if(!other)continue;const current=related.get(other.id)||{node:other,kinds:new Set(),score:0,priority:0};current.kinds.add(link.kind);current.score=Math.max(current.score,link.score||0);current.priority=Math.max(current.priority,precedence[link.kind]||0);related.set(other.id,current)}return [...related.values()].map(item=>({...item,kind:[...item.kinds].sort((a,b)=>(precedence[b]||0)-(precedence[a]||0)).join(" · ")})).sort((a,b)=>(b.priority-a.priority)||(b.score-a.score)||a.node.title.localeCompare(b.node.title))}
function groupLabel(node){if(node.is_session)return "Sessions";if(node.kind==="tag")return "Tags";return {pattern:"Patterns",concept:"Concepts",decision:"Decisions",lesson:"Lessons",snippet:"Snippets",source:"Sources",infra:"Infrastructure"}[node.category]||"Related knowledge"}
function renderRelations(d){const container=document.getElementById("relations"),relations=relationNodes(d);container.replaceChildren();if(!relations.length){const empty=document.createElement("p");empty.className="relations-empty";empty.textContent="No indexed relationships for this node yet.";container.append(empty);return}const groups=new Map(),order=["Patterns","Concepts","Decisions","Lessons","Sessions","Snippets","Sources","Infrastructure","Related knowledge","Tags"];relations.forEach(item=>{const key=groupLabel(item.node);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item)});for(const [label,items] of [...groups].sort((a,b)=>(order.indexOf(a[0])<0?99:order.indexOf(a[0]))-(order.indexOf(b[0])<0?99:order.indexOf(b[0])))){const group=document.createElement("div");group.className="relation-group";const heading=document.createElement("h4");heading.textContent=`${label} · ${items.length}`;group.append(heading);for(const item of items.slice(0,8)){const button=document.createElement("button");button.type="button";button.className="relation-row";button.setAttribute("aria-label",`Focus ${item.node.title}, connected by ${item.kind}`);const dot=document.createElement("i");dot.className=`relation-dot ${item.node.is_session?"session":item.node.category}`;const title=document.createElement("span");title.textContent=item.node.title;const kind=document.createElement("small");kind.textContent=item.kind;button.append(dot,title,kind);button.addEventListener("click",()=>{if(!visibleIds.has(item.node.id))setCollection("all",false);selectNode(item.node,true)});group.append(button)}container.append(group)}}
function selectNode(d,focus){selectedNode=d;nodeSelection.classed("selected",n=>n.id===d.id);document.getElementById("inspector-empty").hidden=true;const content=document.getElementById("detail-content");content.classList.add("is-visible");document.getElementById("detail-kind").textContent=d.is_session?"Codex session":d.category;document.getElementById("detail-title").textContent=d.title;document.getElementById("detail-description").textContent=d.description||`${d.category} node`;document.getElementById("detail-path").textContent=d.path||"";const tags=document.getElementById("detail-tags"),items=[...(d.tags||[])];if(d.project)items.unshift(d.project);if(d.date)items.unshift(d.date.slice(0,16).replace("T"," · "));tags.replaceChildren(...items.map(value=>{const span=document.createElement("span");span.className="badge";span.textContent=value;return span}));const open=document.getElementById("detail-open");open.hidden=!d.url;if(d.url)open.href=d.url;renderRelations(d);document.querySelector(".inspector-scroll").scrollTo({top:0,behavior:motionReduced.matches?"auto":"smooth"});if(focus)focusNode(d);if(innerWidth<=820)openPanel("inspector")}
function clearSelection(){selectedNode=null;nodeSelection.classed("selected",false);document.getElementById("inspector-empty").hidden=false;document.getElementById("detail-content").classList.remove("is-visible")}
function updateCounts(){document.getElementById("counts").textContent=`${visibleNodes.filter(d=>d.kind==="document").length} documents · ${visibleNodes.filter(d=>d.kind==="tag").length} tags · ${activeLinks.length} visible edges`}
function dragStart(event,d){if(!event.active)simulation.alphaTarget(.18).restart();d.fx=d.x;d.fy=d.y}function dragged(event,d){d.fx=event.x;d.fy=event.y}function dragEnd(event,d){if(!event.active)simulation.alphaTarget(0);d.fx=null;d.fy=null}
function search(query){const normalized=query.trim().toLowerCase(),matches=d=>`${d.title} ${d.path} ${d.project||""} ${(d.tags||[]).join(" ")}`.toLowerCase().includes(normalized);nodeSelection.classed("dimmed",d=>normalized&&!matches(d)).classed("match",d=>normalized&&matches(d));document.querySelectorAll(".session-row").forEach(button=>button.classList.toggle("search-hidden",Boolean(normalized)&&!matches(nodeById.get(button.dataset.nodeId))));document.getElementById("search-clear").hidden=!normalized}
function openPanel(panel){workspace.classList.remove("library-open","inspector-open");if(panel)workspace.classList.add(`${panel}-open`);document.getElementById("details-toggle").setAttribute("aria-expanded",String(panel==="inspector"))}
document.querySelectorAll('input[id^="layer-"]').forEach(input=>input.addEventListener("change",updateLinks));document.querySelectorAll("[data-collection]").forEach(button=>button.addEventListener("click",()=>setCollection(button.dataset.collection)));document.querySelectorAll("[data-node-id]").forEach(button=>button.addEventListener("click",()=>{setCollection("all",false);const node=nodeById.get(button.dataset.nodeId);if(node)selectNode(node,true)}));
document.getElementById("fit").addEventListener("click",fit);document.getElementById("library-toggle").addEventListener("click",()=>{if(innerWidth<=820){openPanel(workspace.classList.contains("library-open")?null:"library");return}workspace.classList.toggle("library-collapsed");document.getElementById("library-toggle").setAttribute("aria-expanded",String(!workspace.classList.contains("library-collapsed")))});document.getElementById("details-toggle").addEventListener("click",()=>openPanel(workspace.classList.contains("inspector-open")?null:"inspector"));document.getElementById("sidebar-scrim").addEventListener("click",()=>openPanel(null));document.getElementById("search").addEventListener("input",event=>search(event.target.value));document.getElementById("search-clear").addEventListener("click",()=>{const input=document.getElementById("search");input.value="";search("");input.focus()});document.addEventListener("pointerdown",event=>{const menu=document.getElementById("connection-menu");if(menu.open&&!menu.contains(event.target))menu.open=false});document.addEventListener("keydown",event=>{if(event.key==="Escape"){document.getElementById("connection-menu").open=false;openPanel(null);clearSelection()}});
document.getElementById("scope-label").textContent=`${graph.meta.scope} · ${(graph.meta.collections||[]).join(", ")}`;
new ResizeObserver(()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{size();simulation.alpha(.16).restart()})}).observe(wrap);size();setCollection("all",false);setTimeout(fit,850);
</script>
</body>
</html>'''
    return (
        template.replace("__LIBRARY__", library)
        .replace("__STATIC_GRAPH__", static_graph)
        .replace("__D3_SOURCE__", d3_source)
        .replace("__GRAPH_DATA__", data)
        .replace("__SCOPE_LABEL__", html.escape(scope_label))
        .replace("__INITIAL_STATUS__", html.escape(initial_status))
    )


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--collection", action="append", default=[], help="QMD collection to graph; repeatable")
    selection.add_argument("--all-collections", action="store_true", help="Graph every include-by-default collection")
    parser.add_argument("--scope", choices=("shared", "all"), default="shared", help="Default excludes local and operating files")
    parser.add_argument("--database", type=Path, default=default_database(repository), help="QMD SQLite index")
    parser.add_argument("--output", type=Path, default=repository / ".tmp" / "brain-canvas.html")
    parser.add_argument("--no-semantic", action="store_true", help="Skip QMD vector similarity edges")
    parser.add_argument("--semantic-threshold", type=float, default=0.55)
    parser.add_argument("--semantic-neighbors", type=int, default=2)
    parser.add_argument("--no-open", action="store_true", help="Build without opening a browser")
    parser.add_argument("--dry-run", action="store_true", help="Print graph counts without writing or opening")
    args = parser.parse_args()

    if not 0 <= args.semantic_threshold <= 1:
        parser.error("--semantic-threshold must be between 0 and 1")
    if args.semantic_neighbors < 1:
        parser.error("--semantic-neighbors must be at least 1")
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
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(graph, d3_source), encoding="utf-8")
    print(f"wrote {output}")
    if not args.no_open:
        webbrowser.open(output.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
