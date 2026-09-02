"""Architecture digital-library HTML renderer.

Produces a single self-contained interactive HTML file with:

- a library landing page (cards for all 5 planned diagram types)
- a real **Architecture** view: an interactive vis-network diagram (pan,
  zoom, drag, click-for-detail) with one node per file plus one per external
  dependency actually pulled in, connected by resolved import edges,
  frontend<->backend endpoint-call edges, and file->dependency edges — see
  ``wenuroute/arch/links.py`` for how those are derived
- a real **Sequence** view (derived call chains, rendered as animated SVG
  swimlane diagrams)
- three "coming soon" roadmap placeholders (Data Flow, Lifecycle, Pipeline)

Hand-rolled vanilla CSS/JS, matching the convention established in
``wenuroute/graph.py`` — the only external asset is the vis-network CDN
script, the same one ``graph.py``'s PyVis-based renderer already pulls in.
"""

from __future__ import annotations

import json
from pathlib import Path

from wenuroute.arch.links import build_file_links
from wenuroute.arch.sequence import derive_sequences
from wenuroute.graph import _KIND_LABELS, _LAYER_META, _detect_layer
from wenuroute.models import NodeKind, RouteGraph

_LANE_ORDER = ["frontend", "backend", "mobile", "other"]

_LAYER_COLOURS = {
    "frontend": "#2196F3",
    "backend": "#4CAF50",
    "mobile": "#9C27B0",
    "other": "#607D8B",
}

_EDGE_KIND_COLOURS = {
    "import": "#555577",
    "endpoint": "#FF9800",
    "dependency": "#FFC107",
}

# Only the N most-connected external dependencies are rendered as network
# nodes (see _build_network_data) — beyond that, one hub node (react,
# fastapi, ...) with dozens of edges dominates the physics layout and
# buries the file<->file/file<->backend edges that matter more.
_MAX_DEPENDENCY_NODES = 12


def _short_name(file_path: str) -> str:
    return file_path.replace("\\", "/").rsplit("/", 1)[-1] if file_path else file_path


def _build_architecture_data(code_graph: RouteGraph, dependency_graph: RouteGraph) -> dict:
    # Every parser creates exactly one canonical "this is a real file" MODULE
    # node per file, id'd as f"{file}:0:{file}" (see BaseParser._node_id).
    # Parsers *also* emit synthetic MODULE nodes for unresolved import/require
    # targets (id "import:<raw string>", file=<that same raw, often
    # extension-less string>) so links.py has something to try to resolve.
    # Without this filter those placeholders leak into the architecture view
    # as if they were real files — on a real monorepo this was the majority
    # of "file" boxes shown (see wenuroute/arch/links.py's docstring for why
    # they can't always be resolved: bare package names, path aliases, etc.).
    real_files = {
        node.file
        for node in code_graph.nodes.values()
        if node.kind == NodeKind.MODULE and node.id == f"{node.file}:0:{node.file}"
    }

    files: dict[str, list] = {}
    for node in code_graph.nodes.values():
        if not node.file or node.kind == NodeKind.DEPENDENCY or node.file not in real_files:
            continue
        files.setdefault(node.file, []).append(node)

    lanes_by_key: dict[str, dict] = {
        key: {"key": key, "icon": _LAYER_META.get(key, ("📦", key))[0],
              "label": _LAYER_META.get(key, ("📦", key))[1], "boxes": []}
        for key in _LANE_ORDER
    }
    detail: dict[str, list] = {}
    file_index: dict[str, dict] = {}

    for file_path, nodes in sorted(files.items()):
        layer = _detect_layer(file_path)
        counts: dict[str, int] = {}
        entries = []
        for node in nodes:
            if node.kind != NodeKind.MODULE:
                counts[node.kind.value] = counts.get(node.kind.value, 0) + 1
            entries.append({
                "id": node.id,
                "label": node.label,
                "kind": node.kind.value,
                "line": node.line,
                "params": node.params,
            })
        detail[file_path] = sorted(entries, key=lambda e: e["line"])
        box = {
            "file": file_path,
            "name": _short_name(file_path),
            "layer": layer,
            "counts": counts,
            "total": sum(counts.values()),
        }
        file_index[file_path] = box
        lanes_by_key.setdefault(layer, {
            "key": layer, "icon": _LAYER_META.get(layer, ("📦", layer))[0],
            "label": _LAYER_META.get(layer, ("📦", layer))[1], "boxes": [],
        })["boxes"].append(box)

    lanes = [lanes_by_key[k] for k in _LANE_ORDER if lanes_by_key[k]["boxes"]]
    lanes += [v for k, v in lanes_by_key.items() if k not in _LANE_ORDER and v["boxes"]]

    dependencies = []
    for node in dependency_graph.nodes.values():
        if node.kind != NodeKind.DEPENDENCY:
            continue
        meta = node.metadata or {}
        dependencies.append({
            "name": node.label,
            "ecosystem": node.id.split(":")[1] if node.id.count(":") >= 2 else "",
            "version": meta.get("version"),
            "dev": bool(meta.get("dev")),
            "manifest": meta.get("manifest"),
            "optional_group": meta.get("optional_group"),
        })
    dependencies.sort(key=lambda d: (d["ecosystem"], d["name"]))

    return {
        "lanes": lanes, "detail": detail, "dependencies": dependencies, "files": file_index,
    }


def _build_network_data(arch_data: dict, code_graph: RouteGraph, dependency_graph: RouteGraph) -> dict:
    """Build the {nodes, edges} dataset for the interactive architecture network."""
    links = build_file_links(code_graph, dependency_graph)

    dep_meta = {d["name"]: d for d in arch_data["dependencies"]}

    # A dependency used by dozens of files (react, fastapi, ...) becomes a
    # physics hub that drags the whole layout toward it and buries the more
    # architecturally interesting file<->file/file<->backend edges. Only the
    # most-connected dependencies get graphed as nodes; the rest are "folded"
    # — dropped from the network entirely and surfaced instead as a compact,
    # clickable side list (see _MAX_DEPENDENCY_NODES).
    dep_consumers: dict[str, set[str]] = {}
    for e in links["dependency_edges"]:
        dep_consumers.setdefault(e["target"], set()).add(e["source"])
    ranked_deps = sorted(dep_consumers.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    graphed_dep_names = {name for name, _ in ranked_deps[:_MAX_DEPENDENCY_NODES]}

    folded_dependencies = []
    for name, consumers in ranked_deps[_MAX_DEPENDENCY_NODES:]:
        dep = dep_meta.get(name, {})
        folded_dependencies.append({
            "name": name,
            "version": dep.get("version"),
            "ecosystem": dep.get("ecosystem", ""),
            "consumers": sorted(consumers),
        })
    folded_dependencies.sort(key=lambda d: (-len(d["consumers"]), d["name"]))

    nodes = []
    for file_path, box in arch_data["files"].items():
        colour = _LAYER_COLOURS.get(box["layer"], _LAYER_COLOURS["other"])
        meta_parts = [f"{v} {k}" for k, v in box["counts"].items()]
        nodes.append({
            "id": file_path,
            "kind": "file",
            "label": box["name"],
            "title": file_path + ("\n" + " · ".join(meta_parts) if meta_parts else ""),
            "color": colour,
            "shape": "box",
            "layer": box["layer"],
            "value": max(1, box["total"]),
        })

    for name in graphed_dep_names:
        dep = dep_meta.get(name, {"name": name, "ecosystem": "", "version": None})
        nid = f"dep::{name}"
        title = name + (f" {dep['version']}" if dep.get("version") else "")
        nodes.append({
            "id": nid,
            "kind": "dependency",
            "label": name,
            "title": title,
            "color": _EDGE_KIND_COLOURS["dependency"],
            "shape": "diamond",
            "layer": "dependency",
            "value": 1,
        })

    edges = []
    for e in links["file_edges"]:
        edges.append({
            "from": e["source"], "to": e["target"], "label": e["label"] if e["kind"] == "endpoint" else "",
            "title": e["label"], "color": _EDGE_KIND_COLOURS.get(e["kind"], "#555577"),
            "dashes": e["kind"] == "endpoint", "kind": e["kind"],
        })
    for e in links["dependency_edges"]:
        if e["target"] not in graphed_dep_names:
            continue
        edges.append({
            "from": e["source"], "to": f"dep::{e['target']}", "label": "",
            "title": f"{e['label']} ({e['ecosystem']})", "color": _EDGE_KIND_COLOURS["dependency"],
            "dashes": True, "kind": "dependency",
        })

    return {"nodes": nodes, "edges": edges, "folded_dependencies": folded_dependencies}


_KIND_COLOURS_JS = {
    "ui_element": "#4CAF50", "function": "#2196F3", "endpoint": "#FF9800",
    "sql": "#F44336", "style": "#9C27B0", "event": "#00BCD4",
    "module": "#607D8B", "dependency": "#FFC107", "unknown": "#9E9E9E",
}

_CSS = """\
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; background: #1a1a2e; color: #e0e0e0;
  font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px;
}
#wa-header {
  padding: 14px 22px; background: #12122a; border-bottom: 1px solid #2a2a5a;
  display: flex; align-items: center; justify-content: space-between;
}
#wa-header h1 { font-size: 17px; margin: 0; color: #7aa2f7; font-weight: 700; }
#wa-tabs { display: flex; gap: 6px; padding: 10px 22px; background: #14142c; flex-wrap: wrap; }
.wa-tab {
  padding: 7px 14px; border: 1px solid #3d3d6e; background: #1e1e3f; color: #e0e0e0;
  border-radius: 6px; cursor: pointer; font-size: 13px; transition: background .12s;
}
.wa-tab:hover:not(:disabled) { background: #252550; }
.wa-tab.active { background: #2d3a6e; border-color: #7aa2f7; }
.wa-tab:disabled { opacity: .45; cursor: default; }
main { padding: 22px; }
section[hidden] { display: none !important; }
.wa-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 16px; }
.wa-card {
  background: #12122a; border: 1px solid #2a2a5a; border-radius: 10px; padding: 16px;
  cursor: pointer; transition: border-color .12s;
}
.wa-card:hover { border-color: #7aa2f7; }
.wa-card.wa-soon { cursor: default; opacity: .6; }
.wa-card-icon { font-size: 26px; margin-bottom: 8px; }
.wa-card-title { font-weight: 700; margin-bottom: 4px; }
.wa-card-desc { font-size: 12px; color: #9a9ac0; line-height: 1.5; }
.wa-badge {
  display: inline-block; margin-top: 10px; font-size: 10px; text-transform: uppercase;
  letter-spacing: .6px; padding: 3px 8px; border-radius: 20px;
}
.wa-badge-ready { background: #0d2a1a; color: #6fcf97; border: 1px solid #2e7d4f; }
.wa-badge-soon { background: #2a2210; color: #e0b34d; border: 1px solid #7a5c1e; }
.wa-lane { margin-bottom: 22px; }
.wa-lane-title { font-size: 12px; text-transform: uppercase; letter-spacing: .8px; color: #9a9ac0; margin-bottom: 8px; }
.wa-lane-boxes { display: flex; flex-wrap: wrap; gap: 10px; }
.wa-box {
  background: #12122a; border: 1px solid #2a2a5a; border-radius: 8px; padding: 10px 12px;
  min-width: 150px; cursor: pointer; transition: border-color .12s;
}
.wa-box:hover { border-color: #7aa2f7; }
.wa-box-title { font-weight: 700; font-size: 13px; margin-bottom: 4px; word-break: break-all; }
.wa-box-meta { font-size: 11px; color: #9a9ac0; }
#wa-arch-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
#wa-arch-search {
  padding: 6px 10px; border: 1px solid #3d3d6e; background: #1e1e3f; color: #e0e0e0;
  border-radius: 6px; font-size: 12px; width: 220px;
}
#wa-arch-search-info { font-size: 11px; color: #6272a4; min-width: 70px; }
#wa-arch-filters {
  display: flex; gap: 4px 16px; flex-wrap: wrap; align-items: center;
  margin-bottom: 10px; padding: 8px 10px; background: #14142c; border-radius: 6px;
}
.wa-filter-item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: #c8c8ea; cursor: pointer; }
.wa-filter-item input { cursor: pointer; accent-color: #7aa2f7; }
.wa-legend-dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.wa-legend-dot.wa-legend-diamond { border-radius: 0; transform: rotate(45deg); width: 8px; height: 8px; }
.wa-legend-line { display: inline-block; width: 16px; height: 0; border-top: 2px solid; }
#wa-arch-canvas-wrap {
  background: #12122a; border: 1px solid #2a2a5a; border-radius: 8px;
  height: 62vh; min-height: 380px; position: relative;
}
#wa-arch-network { width: 100%; height: 100%; }
#wa-arch-stats { font-size: 11px; color: #6272a4; padding: 6px 2px; }
#wa-arch-deps-title { font-size: 12px; text-transform: uppercase; letter-spacing: .8px; color: #9a9ac0; margin: 18px 0 8px; }
#wa-arch-folded-title { font-size: 11px; color: #9a9ac0; margin: 14px 0 8px; line-height: 1.5; }
.wa-chip-clickable { cursor: pointer; transition: border-color .12s; }
.wa-chip-clickable:hover { border-color: #7aa2f7; color: #e0e0e0; }
.wa-chip-wrap { display: flex; flex-wrap: wrap; gap: 6px; }
.wa-chip {
  font-size: 11px; padding: 4px 9px; border-radius: 14px; background: #1e1e3f;
  border: 1px solid #3d3d6e; color: #c8c8ea;
}
.wa-chip.wa-chip-dev { opacity: .65; }
#wa-detail {
  position: fixed; top: 0; right: -320px; width: 320px; height: 100vh;
  background: #12122a; border-left: 1px solid #2a2a5a; overflow-y: auto;
  transition: right .2s ease; z-index: 50; padding: 14px;
}
#wa-detail.wa-open { right: 0; }
#wa-detail-close { float: right; background: none; border: none; color: #9a9ac0; font-size: 16px; cursor: pointer; }
#wa-detail h3 { margin: 0 0 10px; color: #e8e8ff; word-break: break-all; }
.wa-detail-item { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 12px; border-bottom: 1px solid #1e1e3f; }
.wa-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
#view-sequence { display: flex; gap: 16px; }
#wa-seq-list { width: 300px; flex-shrink: 0; }
#wa-seq-search {
  width: 100%; padding: 7px 10px; margin-bottom: 10px; border: 1px solid #3d3d6e;
  background: #1e1e3f; color: #e0e0e0; border-radius: 6px; font-size: 12px;
}
.wa-seq-item {
  padding: 8px 10px; border-radius: 6px; cursor: pointer; font-size: 12px;
  margin-bottom: 4px; border: 1px solid transparent; line-height: 1.4;
}
.wa-seq-item:hover { background: #1e1e3f; }
.wa-seq-item.wa-active { background: #2d3a6e; border-color: #7aa2f7; }
#wa-seq-canvas-wrap { flex: 1; overflow: auto; background: #12122a; border: 1px solid #2a2a5a; border-radius: 8px; padding: 12px; }
#wa-seq-toolbar { margin-bottom: 10px; display: flex; gap: 8px; align-items: center; }
.wa-btn {
  padding: 6px 12px; border: 1px solid #3d3d6e; background: #1e1e3f; color: #e0e0e0;
  border-radius: 6px; cursor: pointer; font-size: 12px;
}
.wa-btn:hover { background: #252550; }
.wa-seq-step { opacity: 0; transition: opacity .25s ease; }
.wa-seq-step.wa-visible { opacity: 1; }
.wa-empty { color: #6272a4; font-style: italic; padding: 20px; font-size: 13px; }
</style>"""

_LIBRARY_CARDS = [
    ("architecture", "🏛", "Diagrama de Arquitectura", "Arquitectura",
     "Módulos, capas del proyecto y dependencias externas.", True),
    ("sequence", "🔀", "Diagramas de Secuencia", "Secuencias",
     "Cadenas de llamada: UI/Endpoint → función → SQL.", True),
    ("dataflow", "🌊", "Data Flow Diagram", "Flujo de datos",
     "Flujo de datos entre entidades, procesos y almacenes.", False),
    ("lifecycle", "♻️", "Mapa de Ciclo de Vida", "Ciclo de vida",
     "Ciclo de vida de una petición o entidad a través del sistema.", False),
    ("pipeline", "🛠", "Pipeline Diagram", "Pipeline",
     "Pipelines de build/CI-CD detectados en el proyecto.", False),
]


def _render_library_html() -> str:
    cards = []
    for key, icon, title, _nav_label, desc, ready in _LIBRARY_CARDS:
        cls = "wa-card" if ready else "wa-card wa-soon"
        badge = (
            '<span class="wa-badge wa-badge-ready">✅ Disponible</span>'
            if ready else
            '<span class="wa-badge wa-badge-soon">🚧 Roadmap</span>'
        )
        target = f' data-goto="{key}"' if ready else ""
        cards.append(
            f'<div class="{cls}"{target}>'
            f'<div class="wa-card-icon">{icon}</div>'
            f'<div class="wa-card-title">{title}</div>'
            f'<div class="wa-card-desc">{desc}</div>'
            f'{badge}'
            "</div>"
        )
    return (
        '<section id="view-library">'
        '<p style="color:#9a9ac0;margin:0 0 16px;">'
        'Biblioteca digital de arquitectura, generada automáticamente a partir del código fuente.'
        '</p>'
        f'<div class="wa-cards">{"".join(cards)}</div>'
        "</section>"
    )


def _render_roadmap_section(view_id: str, icon: str, title: str, desc: str) -> str:
    return (
        f'<section id="{view_id}" hidden>'
        '<div class="wa-cards" style="grid-template-columns:1fr;max-width:520px;">'
        '<div class="wa-card wa-soon">'
        f'<div class="wa-card-icon">{icon}</div>'
        f'<div class="wa-card-title">{title}</div>'
        f'<div class="wa-card-desc">{desc}</div>'
        '<span class="wa-badge wa-badge-soon">🚧 Roadmap — aún no implementado</span>'
        "</div></div></section>"
    )


_JS = """\
<script>
(function() {
  var ARCH = __ARCH_DATA__;
  var NET = __NET_DATA__;
  var SEQUENCES = __SEQ_DATA__;
  var KIND_COLOURS = __KIND_COLOURS__;

  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Tabs ─────────────────────────────────────────────────────────────── //
  function goto(view) {
    document.querySelectorAll('section[id^="view-"]').forEach(function(s) {
      s.hidden = (s.id !== 'view-' + view);
    });
    document.querySelectorAll('.wa-tab').forEach(function(btn) {
      btn.classList.toggle('active', btn.dataset.view === view);
    });
  }
  document.querySelectorAll('.wa-tab').forEach(function(btn) {
    if (btn.disabled) return;
    btn.addEventListener('click', function() { goto(btn.dataset.view); });
  });
  document.querySelectorAll('[data-goto]').forEach(function(el) {
    el.addEventListener('click', function() { goto(el.dataset.goto); });
  });

  // ── Architecture view (interactive vis-network diagram) ───────────────── //
  var LAYER_COLOURS = {frontend:'#2196F3', backend:'#4CAF50', mobile:'#9C27B0', other:'#607D8B', dependency:'#FFC107'};
  var LAYER_BG      = {frontend:'#0d2444', backend:'#0d2a1a', mobile:'#220d44', other:'#1a1a3a', dependency:'#2a2210'};
  // Above this many file nodes, directory clustering activates on first paint
  // instead of the flat per-file view — past this size a flat force-directed
  // layout of individual files stops being navigable.
  var AUTO_CLUSTER_THRESHOLD = 80;

  var detailPanel = document.getElementById('wa-detail');
  var archNetwork = null, visNodes = null, visEdges = null;
  var nodeById = {};
  NET.nodes.forEach(function(n) { nodeById[n.id] = n; });
  var degree = {};
  NET.edges.forEach(function(e) {
    degree[e.from] = (degree[e.from] || 0) + 1;
    degree[e.to] = (degree[e.to] || 0) + 1;
  });

  var hiddenLayers = new Set();
  var hiddenEdgeKinds = new Set();
  var showIsolated = false;
  var clustersActive = false;
  var clusterDirMap = {};

  function showFileDetail(file) {
    var items = ARCH.detail[file] || [];
    var html = '<button id="wa-detail-close">✕</button><h3>' + escHtml(file) + '</h3>';
    if (!items.length) {
      html += '<div class="wa-empty">Sin elementos detectados.</div>';
    } else {
      items.forEach(function(it) {
        var c = KIND_COLOURS[it.kind] || '#9E9E9E';
        html += '<div class="wa-detail-item"><span class="wa-dot" style="background:' + c + '"></span>' +
          '<span>' + escHtml(it.label) + ' <span style="color:#6272a4">(' + escHtml(it.kind) +
          (it.line ? ', línea ' + it.line : '') + ')</span></span></div>';
      });
    }
    renderNeighbours(file, html);
  }

  function showDependencyDetail(nodeId, label) {
    var html = '<button id="wa-detail-close">✕</button><h3>🧩 ' + escHtml(label) + '</h3>';
    renderNeighbours(nodeId, html);
  }

  // Folded dependencies aren't graph nodes (see _MAX_DEPENDENCY_NODES), so
  // there's no archNetwork.getConnectedNodes() to lean on — the consumer
  // list travels with the dependency itself instead.
  function showFoldedDependencyDetail(dep) {
    var html = '<button id="wa-detail-close">✕</button><h3>🧩 ' + escHtml(dep.name) +
      (dep.version ? ' <span style="color:#6272a4;font-size:12px;">' + escHtml(dep.version) + '</span>' : '') + '</h3>' +
      '<div class="wa-lane-title">Usado por (' + dep.consumers.length + ')</div>';
    dep.consumers.forEach(function(file) {
      var n = nodeById[file];
      html += '<div class="wa-detail-item" style="cursor:pointer" data-nav="' + escHtml(file) + '">' +
        '<span class="wa-dot" style="background:' + (n ? (LAYER_COLOURS[n.layer] || '#9E9E9E') : '#9E9E9E') + '"></span>' +
        '<span>' + escHtml(file) + '</span></div>';
    });
    detailPanel.innerHTML = html;
    detailPanel.classList.add('wa-open');
    document.getElementById('wa-detail-close').addEventListener('click', function() {
      detailPanel.classList.remove('wa-open');
    });
    detailPanel.querySelectorAll('[data-nav]').forEach(function(el) {
      el.addEventListener('click', function() { selectNode(this.dataset.nav); });
    });
  }

  function showClusterDetail(clusterId, dir, ids) {
    var html = '<button id="wa-detail-close">✕</button><h3>📁 ' + escHtml(dir) + '</h3>' +
      '<div class="wa-lane-title">' + ids.length + ' archivo(s)</div>';
    ids.forEach(function(id) {
      var n = nodeById[id];
      if (!n) return;
      html += '<div class="wa-detail-item" style="cursor:pointer" data-nav="' + escHtml(id) + '">' +
        '<span class="wa-dot" style="background:' + (LAYER_COLOURS[n.layer] || '#9E9E9E') + '"></span>' +
        '<span>' + escHtml(n.label) + '</span></div>';
    });
    detailPanel.innerHTML = html;
    detailPanel.classList.add('wa-open');
    document.getElementById('wa-detail-close').addEventListener('click', function() {
      detailPanel.classList.remove('wa-open');
    });
    detailPanel.querySelectorAll('[data-nav]').forEach(function(el) {
      el.addEventListener('click', function() {
        if (archNetwork.isCluster(clusterId)) archNetwork.openCluster(clusterId);
        selectNode(this.dataset.nav);
      });
    });
  }

  function renderNeighbours(nodeId, htmlSoFar) {
    var html = htmlSoFar;
    if (archNetwork) {
      var connected = archNetwork.getConnectedNodes(nodeId);
      if (connected.length) {
        html += '<div class="wa-lane-title" style="margin-top:14px;">↔ Relacionado con (' + connected.length + ')</div>';
        connected.forEach(function(cid) {
          var n = nodeById[cid];
          if (!n) {
            if (String(cid).indexOf('waDirCluster::') === 0) {
              html += '<div class="wa-detail-item" style="cursor:pointer" data-nav="' + escHtml(cid) + '">' +
                '<span class="wa-dot" style="background:#607D8B"></span><span>📁 ' +
                escHtml(String(cid).replace('waDirCluster::', '')) + '</span></div>';
            }
            return;
          }
          var c = LAYER_COLOURS[n.layer] || '#9E9E9E';
          html += '<div class="wa-detail-item" style="cursor:pointer" data-nav="' + escHtml(cid) + '">' +
            '<span class="wa-dot" style="background:' + c + '"></span><span>' + escHtml(n.label) + '</span></div>';
        });
      }
    }
    detailPanel.innerHTML = html;
    detailPanel.classList.add('wa-open');
    document.getElementById('wa-detail-close').addEventListener('click', function() {
      detailPanel.classList.remove('wa-open');
    });
    detailPanel.querySelectorAll('[data-nav]').forEach(function(el) {
      el.addEventListener('click', function() { selectNode(this.dataset.nav); });
    });
  }

  function selectNode(nodeId) {
    if (!archNetwork) return;
    archNetwork.selectNodes([nodeId]);
    archNetwork.focus(nodeId, {scale: 1.1, animation: {duration: 300, easingFunction: 'easeInOutQuad'}});
    if (archNetwork.isCluster(nodeId)) {
      var dir = String(nodeId).replace('waDirCluster::', '');
      showClusterDetail(nodeId, dir, clusterDirMap[dir] || []);
      return;
    }
    var n = nodeById[nodeId];
    if (!n) return;
    if (n.kind === 'dependency') showDependencyDetail(nodeId, n.label);
    else showFileDetail(nodeId);
  }

  // ── Filters (layer / edge-kind / isolated-node visibility) ────────────── //

  function nodeHidden(n) {
    if (hiddenLayers.has(n.layer)) return true;
    if (!showIsolated && n.kind === 'file' && !degree[n.id]) return true;
    return false;
  }

  function applyFilters() {
    if (!visNodes) return;
    var hiddenIds = {};
    NET.nodes.forEach(function(n) { hiddenIds[n.id] = nodeHidden(n); });
    visNodes.update(NET.nodes.map(function(n) { return {id: n.id, hidden: hiddenIds[n.id]}; }));
    visEdges.update(NET.edges.map(function(e, i) {
      var hide = hiddenEdgeKinds.has(e.kind) || hiddenIds[e.from] || hiddenIds[e.to];
      return {id: i, hidden: !!hide};
    }));
    updateStats();
  }

  function updateStats() {
    var el = document.getElementById('wa-arch-stats');
    if (!el) return;
    var totalFiles = NET.nodes.filter(function(n) { return n.kind === 'file'; }).length;
    var visibleFiles = NET.nodes.filter(function(n) { return n.kind === 'file' && !nodeHidden(n); }).length;
    var html = 'Archivos: <b>' + visibleFiles + '</b> / ' + totalFiles;
    if (clustersActive) {
      html += ' · Carpetas agrupadas: <b>' + Object.keys(clusterDirMap).length + '</b>';
    }
    el.innerHTML = html;
  }

  document.getElementById('wa-arch-filters').addEventListener('change', function(e) {
    var t = e.target;
    if (t.dataset.layer) {
      if (t.checked) hiddenLayers.delete(t.dataset.layer); else hiddenLayers.add(t.dataset.layer);
      applyFilters();
    } else if (t.dataset.edgekind) {
      if (t.checked) hiddenEdgeKinds.delete(t.dataset.edgekind); else hiddenEdgeKinds.add(t.dataset.edgekind);
      applyFilters();
    } else if (t.id === 'wa-arch-show-isolated') {
      showIsolated = t.checked;
      applyFilters();
    }
  });

  // ── Search ──────────────────────────────────────────────────────────── //

  document.getElementById('wa-arch-search').addEventListener('input', function() {
    var q = this.value.trim().toLowerCase();
    var infoEl = document.getElementById('wa-arch-search-info');
    if (!archNetwork) return;
    if (!q) { infoEl.textContent = ''; return; }
    var matches = NET.nodes.filter(function(n) {
      return n.label.toLowerCase().indexOf(q) !== -1 || n.id.toLowerCase().indexOf(q) !== -1;
    });
    infoEl.textContent = matches.length + ' resultado(s)';
    if (!matches.length) return;
    var visibleIds = {};
    matches.forEach(function(n) {
      try {
        var stack = archNetwork.findNode(n.id);
        var vid = stack && stack.length ? stack[stack.length - 1] : n.id;
        visibleIds[vid] = true;
      } catch (e) { visibleIds[n.id] = true; }
    });
    var ids = Object.keys(visibleIds);
    archNetwork.selectNodes(ids);
    if (ids.length <= 40) {
      archNetwork.fit({nodes: ids, animation: {duration: 400, easingFunction: 'easeInOutQuad'}});
    }
  });

  // ── Directory clustering ───────────────────────────────────────────────── //

  NET.nodes.forEach(function(n) {
    if (n.kind !== 'file') return;
    var slash = n.id.lastIndexOf('/');
    var dir = slash === -1 ? '(raíz)' : n.id.slice(0, slash);
    (clusterDirMap[dir] = clusterDirMap[dir] || []).push(n.id);
  });
  Object.keys(clusterDirMap).forEach(function(d) {
    if (clusterDirMap[d].length < 2) delete clusterDirMap[d];
  });

  function activateClustering() {
    Object.keys(clusterDirMap).forEach(function(dir) {
      var ids = clusterDirMap[dir];
      var layerCounts = {};
      ids.forEach(function(id) {
        var n = nodeById[id];
        if (n) layerCounts[n.layer] = (layerCounts[n.layer] || 0) + 1;
      });
      var domLayer = Object.keys(layerCounts).sort(function(a, b) { return layerCounts[b] - layerCounts[a]; })[0] || 'other';
      var shortDir = dir === '(raíz)' ? dir : dir.split('/').pop();
      archNetwork.cluster({
        joinCondition: (function(idSet) { return function(opts) { return idSet.indexOf(opts.id) !== -1; }; })(ids),
        clusterNodeProperties: {
          id: 'waDirCluster::' + dir,
          label: shortDir + ' (' + ids.length + ')',
          shape: 'square', borderDashes: [6, 3], borderWidth: 2,
          color: {
            background: LAYER_BG[domLayer] || LAYER_BG.other,
            border: LAYER_COLOURS[domLayer] || LAYER_COLOURS.other,
            highlight: {background: '#2a2a6a', border: '#aaaaff'},
          },
          size: Math.min(20 + ids.length * 1.5, 46),
          font: {color: '#e0e0e0', size: 12, bold: true},
          title: dir + '\n' + ids.length + ' archivo(s)\ndoble clic para expandir',
        },
      });
    });
    clustersActive = true;
    document.getElementById('wa-arch-cluster-btn').textContent = '📂 Desagrupar todo';
    updateStats();
  }

  function deactivateClustering() {
    for (var limit = 300; limit > 0; limit--) {
      var found = false;
      visNodes.getIds().forEach(function(nid) {
        if (archNetwork.isCluster(nid)) { archNetwork.openCluster(nid); found = true; }
      });
      if (!found) break;
    }
    clustersActive = false;
    document.getElementById('wa-arch-cluster-btn').textContent = '📁 Agrupar por carpeta';
    updateStats();
  }

  document.getElementById('wa-arch-cluster-btn').addEventListener('click', function() {
    if (clustersActive) deactivateClustering(); else activateClustering();
    archNetwork.fit({animation: {duration: 500, easingFunction: 'easeInOutQuad'}});
  });

  var archRoot = document.getElementById('wa-architecture-body');
  if (!NET.nodes.length) {
    archRoot.innerHTML = '<div class="wa-empty">No se detectaron módulos ni dependencias.</div>';
  } else {
    var container = document.getElementById('wa-arch-network');
    visNodes = new vis.DataSet(NET.nodes.map(function(n) {
      return {
        id: n.id, label: n.label, title: n.title, shape: n.shape,
        color: {background: n.color, border: n.color, highlight: {background: '#2a2a6a', border: '#aaaaff'}},
        font: {color: '#e0e0e0', size: 12},
        size: n.shape === 'diamond' ? 14 : Math.min(14 + n.value * 1.5, 34),
      };
    }));
    visEdges = new vis.DataSet(NET.edges.map(function(e, i) {
      return {
        id: i, from: e.from, to: e.to, label: e.label, title: e.title,
        arrows: {to: {enabled: true, scaleFactor: 0.5}},
        color: {color: e.color, highlight: '#aaaaff'},
        dashes: e.dashes, font: {size: 9, color: '#888', strokeWidth: 0, align: 'middle'},
        smooth: {type: 'dynamic'},
      };
    }));

    archNetwork = new vis.Network(container, {nodes: visNodes, edges: visEdges}, {
      physics: {
        enabled: true, solver: 'forceAtlas2Based',
        forceAtlas2Based: {gravitationalConstant: -70, centralGravity: 0.01, springLength: 130, springConstant: 0.08},
        stabilization: {iterations: 150},
      },
      interaction: {hover: true, navigationButtons: true, tooltipDelay: 150},
      layout: {improvedLayout: true},
    });

    applyFilters();
    if (Object.keys(clusterDirMap).length && NET.nodes.filter(function(n) { return n.kind === 'file'; }).length > AUTO_CLUSTER_THRESHOLD) {
      activateClustering();
    }

    archNetwork.once('stabilized', function() {
      setTimeout(function() { archNetwork.setOptions({physics: {enabled: false}}); }, 300);
    });

    archNetwork.on('doubleClick', function(params) {
      if (params.nodes.length === 1 && archNetwork.isCluster(params.nodes[0])) {
        archNetwork.openCluster(params.nodes[0]);
        updateStats();
      }
    });

    archNetwork.on('click', function(params) {
      if (params.nodes.length === 1) selectNode(params.nodes[0]);
      else detailPanel.classList.remove('wa-open');
    });

    document.getElementById('wa-arch-fit').addEventListener('click', function() {
      archNetwork.fit({animation: {duration: 400, easingFunction: 'easeInOutQuad'}});
    });
    var physOn = false;
    var physBtn = document.getElementById('wa-arch-physics');
    physBtn.addEventListener('click', function() {
      physOn = !physOn;
      archNetwork.setOptions({physics: {enabled: physOn}});
      physBtn.textContent = physOn ? '⏸ Pausar física' : '▶ Activar física';
    });
  }

  if (NET.folded_dependencies && NET.folded_dependencies.length) {
    var foldedRoot = document.getElementById('wa-arch-folded-deps');
    foldedRoot.innerHTML = '<div id="wa-arch-folded-title">🧩 Otras dependencias usadas, no graficadas (' +
      NET.folded_dependencies.length + ') — solo las más conectadas se muestran en el diagrama; ' +
      'clic para ver quién las usa</div>';
    var foldedWrap = document.createElement('div');
    foldedWrap.className = 'wa-chip-wrap';
    NET.folded_dependencies.forEach(function(dep) {
      var chip = document.createElement('span');
      chip.className = 'wa-chip wa-chip-clickable';
      chip.title = dep.consumers.length + ' archivo(s)' + (dep.version ? ' · ' + dep.version : '');
      chip.textContent = dep.name + ' (' + dep.consumers.length + ')';
      chip.addEventListener('click', function() { showFoldedDependencyDetail(dep); });
      foldedWrap.appendChild(chip);
    });
    foldedRoot.appendChild(foldedWrap);
  }

  if (ARCH.dependencies.length) {
    var depsRoot = document.getElementById('wa-arch-deps');
    depsRoot.innerHTML = '<div id="wa-arch-deps-title">📦 Todas las dependencias declaradas (' + ARCH.dependencies.length + ')</div>';
    var chipWrap = document.createElement('div');
    chipWrap.className = 'wa-chip-wrap';
    ARCH.dependencies.forEach(function(dep) {
      var chip = document.createElement('span');
      chip.className = 'wa-chip' + (dep.dev ? ' wa-chip-dev' : '');
      chip.title = (dep.manifest || '') + (dep.version ? ' ' + dep.version : '');
      chip.textContent = dep.name + (dep.version ? ' ' + dep.version : '');
      chipWrap.appendChild(chip);
    });
    depsRoot.appendChild(chipWrap);
  }

  // ── Sequence view ────────────────────────────────────────────────────── //
  var seqListEl = document.getElementById('wa-seq-list-items');
  var seqCanvas = document.getElementById('wa-seq-canvas');
  var playTimer = null;

  function renderSeqList(filter) {
    seqListEl.innerHTML = '';
    var q = (filter || '').toLowerCase();
    SEQUENCES.filter(function(s) { return !q || s.title.toLowerCase().indexOf(q) !== -1; })
      .forEach(function(seq) {
        var item = document.createElement('div');
        item.className = 'wa-seq-item';
        item.dataset.id = seq.id;
        item.textContent = seq.title;
        item.addEventListener('click', function() {
          document.querySelectorAll('.wa-seq-item').forEach(function(el) { el.classList.remove('wa-active'); });
          item.classList.add('wa-active');
          renderSequenceSvg(seq);
        });
        seqListEl.appendChild(item);
      });
  }

  document.getElementById('wa-seq-search').addEventListener('input', function() {
    renderSeqList(this.value);
  });

  function participantKey(step, singleFile) {
    return singleFile ? step.kind : (step.file || step.kind);
  }

  function renderSequenceSvg(seq) {
    if (playTimer) { clearInterval(playTimer); playTimer = null; }
    var steps = seq.steps;
    var files = {};
    steps.forEach(function(s) { if (s.file) files[s.file] = true; });
    var singleFile = Object.keys(files).length <= 1;

    var participants = [];
    var seen = {};
    steps.forEach(function(s) {
      var key = participantKey(s, singleFile);
      if (!seen[key]) { seen[key] = true; participants.push(key); }
    });

    var LANE_W = 190, STEP_H = 60, TOP = 70, MARGIN = 20;
    var width = MARGIN * 2 + Math.max(1, participants.length - 1) * LANE_W + 40;
    var height = TOP + steps.length * STEP_H + 30;
    var xFor = {};
    participants.forEach(function(p, i) { xFor[p] = MARGIN + i * LANE_W + 20; });

    var svg = '<svg width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '">';
    svg += '<defs><marker id="wa-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">' +
           '<path d="M0,0 L6,3 L0,6 Z" fill="#7aa2f7"/></marker></defs>';

    participants.forEach(function(p) {
      var x = xFor[p];
      svg += '<rect x="' + (x - 65) + '" y="10" width="130" height="34" rx="6" fill="#1e1e3f" stroke="#3d3d6e"/>';
      svg += '<text x="' + x + '" y="31" text-anchor="middle" fill="#e0e0e0" font-size="11">' +
             escHtml(p.length > 22 ? '…' + p.slice(-20) : p) + '</text>';
      svg += '<line x1="' + x + '" y1="44" x2="' + x + '" y2="' + (height - 15) + '" stroke="#3d3d6e" stroke-width="1.5"/>';
    });

    for (var i = 0; i < steps.length; i++) {
      var y = TOP + i * STEP_H;
      var cur = xFor[participantKey(steps[i], singleFile)];
      var prev = i === 0 ? cur : xFor[participantKey(steps[i - 1], singleFile)];
      var label = (steps[i].edge_label ? steps[i].edge_label + ': ' : (i === 0 ? '▶ ' : '')) + steps[i].label;
      var kindColour = KIND_COLOURS[steps[i].kind] || '#9E9E9E';

      svg += '<g class="wa-seq-step" data-index="' + i + '">';
      if (i > 0 && prev === cur) {
        // self-call loop
        svg += '<path d="M' + cur + ',' + y + ' C' + (cur + 40) + ',' + (y - 10) + ' ' + (cur + 40) + ',' + (y + 10) + ' ' + cur + ',' + y + '" ' +
               'fill="none" stroke="#7aa2f7" stroke-width="1.5" marker-end="url(#wa-arrow)"/>';
        svg += '<text x="' + (cur + 46) + '" y="' + (y + 4) + '" font-size="10" fill="#9a9ac0">' + escHtml(label) + '</text>';
      } else {
        svg += '<line x1="' + prev + '" y1="' + y + '" x2="' + cur + '" y2="' + y + '" stroke="#7aa2f7" stroke-width="1.5" marker-end="url(#wa-arrow)"/>';
        var midx = (prev + cur) / 2;
        svg += '<text x="' + midx + '" y="' + (y - 6) + '" text-anchor="middle" font-size="10" fill="#9a9ac0">' + escHtml(label) + '</text>';
      }
      svg += '<circle cx="' + cur + '" cy="' + y + '" r="4" fill="' + kindColour + '"/>';
      svg += '</g>';
    }
    svg += '</svg>';

    seqCanvas.innerHTML = svg;
  }

  document.getElementById('wa-seq-play').addEventListener('click', function() {
    var steps = document.querySelectorAll('.wa-seq-step');
    steps.forEach(function(s) { s.classList.remove('wa-visible'); });
    if (playTimer) clearInterval(playTimer);
    var i = 0;
    playTimer = setInterval(function() {
      if (i >= steps.length) { clearInterval(playTimer); playTimer = null; return; }
      steps[i].classList.add('wa-visible');
      i++;
    }, 400);
  });
  document.getElementById('wa-seq-reset').addEventListener('click', function() {
    if (playTimer) { clearInterval(playTimer); playTimer = null; }
    document.querySelectorAll('.wa-seq-step').forEach(function(s) { s.classList.add('wa-visible'); });
  });

  renderSeqList('');
  if (SEQUENCES.length) {
    var first = seqListEl.querySelector('.wa-seq-item');
    if (first) first.click();
  } else {
    seqCanvas.innerHTML = '<div class="wa-empty">No se detectaron cadenas de llamada.</div>';
  }
})();
</script>"""


def render_arch_html(code_graph: RouteGraph, dependency_graph: RouteGraph, output: Path) -> None:
    """Render the architecture digital-library HTML at *output*.

    Library landing page + real Architecture and Sequence views, plus
    roadmap placeholders for Data Flow / Lifecycle / Pipeline.
    """
    arch_data = _build_architecture_data(code_graph, dependency_graph)
    net_data = _build_network_data(arch_data, code_graph, dependency_graph)

    full_graph = RouteGraph()
    full_graph.merge(code_graph)
    full_graph.merge(dependency_graph)
    sequences = derive_sequences(full_graph)

    nav_buttons = ['<button class="wa-tab active" data-view="library">📚 Library</button>']
    for key, icon, _title, nav_label, _desc, ready in _LIBRARY_CARDS:
        disabled = "" if ready else " disabled"
        nav_buttons.append(
            f'<button class="wa-tab" data-view="{key}"{disabled}>{icon} {nav_label}'
            f'{"" if ready else " (soon)"}</button>'
        )

    layer_meta = {**_LAYER_META, "dependency": ("🧩", "Dependencia")}
    edge_kind_meta = {"import": "Import", "endpoint": "Llamada API", "dependency": "Depende de"}
    present_layers = sorted({n["layer"] for n in net_data["nodes"]})
    present_edge_kinds = sorted({e["kind"] for e in net_data["edges"]})

    layer_filter_items = "".join(
        f'<label class="wa-filter-item">'
        f'<input type="checkbox" checked data-layer="{layer}">'
        f'<span class="wa-legend-dot" style="background:{_LAYER_COLOURS.get(layer, _EDGE_KIND_COLOURS["dependency"])}"></span>'
        f'{layer_meta.get(layer, ("📦", layer))[0]} {layer_meta.get(layer, ("📦", layer))[1]}'
        "</label>"
        for layer in present_layers
    )
    edge_filter_items = "".join(
        f'<label class="wa-filter-item">'
        f'<input type="checkbox" checked data-edgekind="{kind}">'
        f'<span class="wa-legend-line" style="border-color:{_EDGE_KIND_COLOURS.get(kind, "#555577")};'
        f'{"border-top-style:dashed" if kind != "import" else ""}"></span>'
        f'{edge_kind_meta.get(kind, kind)}'
        "</label>"
        for kind in present_edge_kinds
    )
    connected_ids = {e["from"] for e in net_data["edges"]} | {e["to"] for e in net_data["edges"]}
    isolated_count = sum(
        1 for n in net_data["nodes"] if n["kind"] == "file" and n["id"] not in connected_ids
    )

    sections = [_render_library_html()]
    sections.append(
        '<section id="view-architecture" hidden>'
        '<div id="wa-architecture-body">'
        '<div id="wa-arch-toolbar">'
        '<input type="text" id="wa-arch-search" placeholder="Buscar archivo o carpeta…">'
        '<span id="wa-arch-search-info"></span>'
        '<button class="wa-btn" id="wa-arch-fit">⊞ Encuadrar todo</button>'
        '<button class="wa-btn" id="wa-arch-physics">▶ Activar física</button>'
        '<button class="wa-btn" id="wa-arch-cluster-btn">📁 Agrupar por carpeta</button>'
        "</div>"
        '<div id="wa-arch-filters">'
        f'{layer_filter_items}{edge_filter_items}'
        '<label class="wa-filter-item">'
        '<input type="checkbox" id="wa-arch-show-isolated">'
        f'Mostrar nodos aislados ({isolated_count})'
        "</label>"
        "</div>"
        '<div id="wa-arch-canvas-wrap"><div id="wa-arch-network"></div></div>'
        '<div id="wa-arch-stats"></div>'
        '<div id="wa-arch-folded-deps"></div>'
        '<div id="wa-arch-deps"></div>'
        "</div>"
        "</section>"
    )
    sections.append(
        '<section id="view-sequence" hidden>'
        '<div id="wa-seq-list">'
        '<input type="text" id="wa-seq-search" placeholder="Buscar secuencia…">'
        '<div id="wa-seq-list-items"></div>'
        "</div>"
        '<div id="wa-seq-canvas-wrap">'
        '<div id="wa-seq-toolbar">'
        '<button class="wa-btn" id="wa-seq-play">▶ Reproducir</button>'
        '<button class="wa-btn" id="wa-seq-reset">↺ Mostrar todo</button>'
        "</div>"
        '<div id="wa-seq-canvas"></div>'
        "</div>"
        "</section>"
    )
    for key, icon, title, _nav_label, desc, ready in _LIBRARY_CARDS:
        if ready:
            continue
        sections.append(_render_roadmap_section(f"view-{key}", icon, title, desc))

    # arch_data["files"] isn't needed client-side (folded into NET already) —
    # drop it before serialising to keep the payload lean.
    arch_data_out = {k: v for k, v in arch_data.items() if k != "files"}

    js = (
        _JS
        .replace("__ARCH_DATA__", json.dumps(arch_data_out, ensure_ascii=False))
        .replace("__NET_DATA__", json.dumps(net_data, ensure_ascii=False))
        .replace("__SEQ_DATA__", json.dumps(sequences, ensure_ascii=False))
        .replace("__KIND_COLOURS__", json.dumps(_KIND_COLOURS_JS, ensure_ascii=False))
    )

    vis_cdn = (
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/vis-network.min.js"></script>'
    )

    html = (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        f"<title>WenuRoute — Architecture Library</title>{vis_cdn}{_CSS}</head><body>"
        '<div id="wa-header"><h1>⚡ WenuRoute — Architecture Library</h1></div>'
        f'<div id="wa-tabs">{"".join(nav_buttons)}</div>'
        f'<main>{"".join(sections)}</main>'
        '<div id="wa-detail"></div>'
        f"{js}"
        "</body></html>"
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
