"""Cross-file relationship resolution for the architecture diagram.

The raw :class:`~wenuroute.models.RouteGraph` never links one file directly
to another: an ``imports`` edge points from a module node to a synthetic
``import:<string>`` node holding the raw import text, and an API call
(``fetch('/api/users')`` on the frontend, ``@app.get('/api/users')`` on the
backend) is two independent edges into the same ``endpoint:...`` node rather
than a single connection between the two files.

This module turns those into real file-to-file and file-to-dependency edges
so the architecture view can render an actual diagram instead of a list of
unconnected boxes. Resolution is best-effort — same tolerant, regex/AST-first
spirit as the parsers: a miss just means no edge is drawn, never an error.

Endpoint bridging in particular can't rely on exact node-id equality: a
frontend call to ``/api/v1/products`` and a backend route declared as
``/products`` (the version/API prefix usually gets added where the router is
*mounted*, e.g. ``app.include_router(router, prefix="/api/v1")``, which none
of the parsers track) refer to the same endpoint but produce different
``endpoint:...`` node ids. ``_tail_match`` compares normalised path segments
instead, requiring the shorter path to be a full trailing match of the
longer one, with dynamic segments (``{id}``, ``:id``, ``${id}``) treated as
wildcards.
"""

from __future__ import annotations

import posixpath
import re

from wenuroute.models import NodeKind, RouteGraph

_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

# "navigates" (React Router <Route>/<Link>, <a href>) is client-side routing,
# not a network request — bridging it to the backend would connect files
# that merely happen to share a URL string, not files with a real runtime
# dependency. Only outbound requests count as a "call".
_CALL_EDGE_LABELS = {"calls", "submits"}
_DEFINE_EDGE_LABELS = {"defines"}

_DYNAMIC_SEGMENT = re.compile(r"^[:{$<].*|.*[}>]$")

# Safety cap: skip fuzzy tail-matching (O(definers * callers)) past this many
# candidate pairs rather than let a huge project stall the render.
_MAX_ENDPOINT_PAIRS = 200_000


def _parse_endpoint_id(ep_id: str) -> tuple[str, str]:
    """Split an ``endpoint:...`` node id into ``(METHOD, raw_path)``.

    Most parsers emit ``endpoint:{METHOD}:{route}``; the HTML parser's plain
    ``<a href>`` case emits just ``endpoint:{href}`` (no method segment).
    """
    parts = ep_id.split(":", 2)
    if len(parts) == 3:
        return parts[1].upper(), parts[2]
    if len(parts) == 2:
        return "", parts[1]
    return "", ep_id


def _normalise_path(raw_path: str) -> tuple[str, ...]:
    path = raw_path.split("?", 1)[0].strip("/")
    if not path:
        return ()
    segments = []
    for seg in path.split("/"):
        if not seg:
            continue
        segments.append("*" if _DYNAMIC_SEGMENT.match(seg) else seg.lower())
    return tuple(segments)


def _tail_match(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """True if the shorter path is a wildcard-tolerant suffix of the longer one.

    Requires at least one *literal* (non-wildcard) segment to agree — a route
    that's nothing but a single ``{id}``-style segment would otherwise tail-
    match almost every other endpoint, flooding the diagram with bogus edges.
    """
    if not a or not b:
        return False
    n = min(len(a), len(b))
    literal_match = False
    for i in range(1, n + 1):
        x, y = a[-i], b[-i]
        if x == "*" or y == "*":
            continue
        if x != y:
            return False
        literal_match = True
    return literal_match


def _js_candidates(from_file: str, imported: str) -> list[str]:
    if imported.startswith("."):
        joined = posixpath.normpath(posixpath.join(posixpath.dirname(from_file), imported))
    elif imported.startswith("/"):
        joined = imported.lstrip("/")
    else:
        return []  # bare package specifier — handled as an external dependency instead

    candidates = [joined]
    for ext in _JS_EXTS:
        candidates.append(joined + ext)
        candidates.append(posixpath.join(joined, "index" + ext))
    return candidates


def _py_candidates(from_file: str, dotted: str) -> list[str]:
    level = len(dotted) - len(dotted.lstrip("."))
    rest = dotted[level:]
    parts = rest.split(".") if rest else []

    if level == 0:
        base_parts: list[str] = []
    else:
        dir_parts = posixpath.dirname(from_file).split("/") if "/" in from_file else []
        up = level - 1
        base_parts = dir_parts[:-up] if up and up <= len(dir_parts) else (dir_parts if not up else [])

    joined = "/".join(p for p in base_parts + parts if p)
    if not joined:
        return []
    return [joined + ".py", posixpath.join(joined, "__init__.py")]


def _resolve_internal(from_file: str, imported: str, files: set[str]) -> str | None:
    candidates = (
        _py_candidates(from_file, imported)
        if from_file.endswith(".py")
        else _js_candidates(from_file, imported)
    )
    for cand in candidates:
        if cand in files:
            return cand
    return None


def _external_root(imported: str) -> str | None:
    """Best-guess package-manager root name for a bare (non-relative) import."""
    if imported.startswith(".") or imported.startswith("/"):
        return None
    if imported.startswith("@"):  # npm scoped package, e.g. "@mui/material"
        segs = imported.split("/")
        return "/".join(segs[:2]) if len(segs) >= 2 else imported
    return imported.split("/")[0].split(".")[0]


def build_file_links(code_graph: RouteGraph, dependency_graph: RouteGraph) -> dict:
    """Derive file-to-file and file-to-dependency edges for the architecture network.

    Returns ``{"file_edges": [...], "dependency_edges": [...]}`` where each
    entry is ``{"source": file, "target": file_or_dep_name, "label": str,
    "kind": "import" | "endpoint"}``. Dependency edges additionally carry
    ``"ecosystem"``.
    """
    files = {n.file for n in code_graph.nodes.values() if n.kind == NodeKind.MODULE and n.file}

    dep_by_name: dict[str, list[dict]] = {}
    for node in dependency_graph.nodes.values():
        if node.kind != NodeKind.DEPENDENCY:
            continue
        ecosystem = node.id.split(":")[1] if node.id.count(":") >= 2 else ""
        dep_by_name.setdefault(node.label.lower(), []).append(
            {"name": node.label, "ecosystem": ecosystem}
        )

    file_edges: set[tuple[str, str, str, str]] = set()
    dependency_edges: set[tuple[str, str, str, str]] = set()

    # ── import edges ──────────────────────────────────────────────────── #
    for edge in code_graph.edges:
        if edge.label != "imports":
            continue
        source = code_graph.nodes.get(edge.source_id)
        target = code_graph.nodes.get(edge.target_id)
        if not source or not target or source.kind != NodeKind.MODULE or not source.file:
            continue
        imported = target.label

        resolved = _resolve_internal(source.file, imported, files)
        if resolved and resolved != source.file:
            file_edges.add((source.file, resolved, "imports", "import"))
            continue

        root = _external_root(imported)
        if not root:
            continue
        matches = dep_by_name.get(root.lower())
        if matches:
            dep = matches[0]
            dependency_edges.add((source.file, dep["name"], "imports", dep["ecosystem"]))

    # ── endpoint-bridging edges (frontend caller file <-> backend definer file) ── #
    # (method, segments, file, raw_label) per side, exact-id duplicates collapsed.
    definers: dict[tuple[str, str, str], str] = {}
    callers: dict[tuple[str, str, str], str] = {}

    for edge in code_graph.edges:
        node = code_graph.nodes.get(edge.target_id)
        if not node or node.kind != NodeKind.ENDPOINT:
            continue
        src = code_graph.nodes.get(edge.source_id)
        if not src or not src.file:
            continue
        method, raw_path = _parse_endpoint_id(node.id)
        key = (method, raw_path, src.file)
        if edge.label in _DEFINE_EDGE_LABELS:
            definers[key] = node.label
        elif edge.label in _CALL_EDGE_LABELS:
            callers[key] = node.label

    definer_list = [(m, _normalise_path(p), f, lbl) for (m, p, f), lbl in definers.items()]
    caller_list = [(m, _normalise_path(p), f, lbl) for (m, p, f), lbl in callers.items()]

    if len(definer_list) * len(caller_list) <= _MAX_ENDPOINT_PAIRS:
        for c_method, c_segs, c_file, c_label in caller_list:
            for d_method, d_segs, d_file, d_label in definer_list:
                if c_file == d_file:
                    continue
                if c_method and d_method and c_method != d_method:
                    continue
                if not _tail_match(c_segs, d_segs):
                    continue
                file_edges.add((c_file, d_file, d_label, "endpoint"))

    return {
        "file_edges": [
            {"source": s, "target": t, "label": lbl, "kind": k} for s, t, lbl, k in sorted(file_edges)
        ],
        "dependency_edges": [
            {"source": s, "target": t, "label": lbl, "ecosystem": eco}
            for s, t, lbl, eco in sorted(dependency_edges)
        ],
    }
