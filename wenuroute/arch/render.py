"""Architecture digital-library HTML renderer.

Produces a single self-contained interactive HTML file with:

- a library landing page (cards for all 5 planned diagram types)
- a real **Architecture** view (modules grouped by layer/file, plus an
  "External Dependencies" section from the manifest scan)
- a real **Sequence** view (derived call chains, rendered as animated SVG
  swimlane diagrams)
- three "coming soon" roadmap placeholders (Data Flow, Lifecycle, Pipeline)

No frameworks, no CDN, no build step — hand-rolled vanilla CSS/JS, matching
the convention established in ``wenuroute/graph.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from wenuroute.arch.sequence import derive_sequences
from wenuroute.graph import _KIND_LABELS, _LAYER_META, _detect_layer
from wenuroute.models import NodeKind, RouteGraph

_LANE_ORDER = ["frontend", "backend", "mobile", "other"]


def _short_name(file_path: str) -> str:
    return file_path.replace("\\", "/").rsplit("/", 1)[-1] if file_path else file_path


def _build_architecture_data(code_graph: RouteGraph, dependency_graph: RouteGraph) -> dict:
    files: dict[str, list] = {}
    for node in code_graph.nodes.values():
        if not node.file or node.kind == NodeKind.DEPENDENCY:
            continue
        files.setdefault(node.file, []).append(node)

    lanes_by_key: dict[str, dict] = {
        key: {"key": key, "icon": _LAYER_META.get(key, ("📦", key))[0],
              "label": _LAYER_META.get(key, ("📦", key))[1], "boxes": []}
        for key in _LANE_ORDER
    }
    detail: dict[str, list] = {}

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
        lanes_by_key.setdefault(layer, {
            "key": layer, "icon": _LAYER_META.get(layer, ("📦", layer))[0],
            "label": _LAYER_META.get(layer, ("📦", layer))[1], "boxes": [],
        })["boxes"].append({
            "file": file_path,
            "name": _short_name(file_path),
            "counts": counts,
            "total": sum(counts.values()),
        })

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

    return {"lanes": lanes, "detail": detail, "dependencies": dependencies}


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

  // ── Architecture view ───────────────────────────────────────────────── //
  var archRoot = document.getElementById('wa-architecture-body');
  ARCH.lanes.forEach(function(lane) {
    var laneEl = document.createElement('div');
    laneEl.className = 'wa-lane';
    var title = document.createElement('div');
    title.className = 'wa-lane-title';
    title.textContent = lane.icon + ' ' + lane.label + ' (' + lane.boxes.length + ')';
    laneEl.appendChild(title);
    var boxesEl = document.createElement('div');
    boxesEl.className = 'wa-lane-boxes';
    lane.boxes.forEach(function(box) {
      var boxEl = document.createElement('div');
      boxEl.className = 'wa-box';
      var metaParts = [];
      Object.keys(box.counts).forEach(function(k) {
        metaParts.push(box.counts[k] + ' ' + k);
      });
      boxEl.innerHTML =
        '<div class="wa-box-title">' + escHtml(box.name) + '</div>' +
        '<div class="wa-box-meta">' + escHtml(metaParts.join(' · ') || 'sin elementos') + '</div>';
      boxEl.addEventListener('click', function() { showFileDetail(box.file); });
      boxesEl.appendChild(boxEl);
    });
    laneEl.appendChild(boxesEl);
    archRoot.appendChild(laneEl);
  });

  if (ARCH.dependencies.length) {
    var depsLane = document.createElement('div');
    depsLane.className = 'wa-lane';
    var depsTitle = document.createElement('div');
    depsTitle.className = 'wa-lane-title';
    depsTitle.textContent = '📦 External Dependencies (' + ARCH.dependencies.length + ')';
    depsLane.appendChild(depsTitle);
    var chipWrap = document.createElement('div');
    chipWrap.className = 'wa-chip-wrap';
    ARCH.dependencies.forEach(function(dep) {
      var chip = document.createElement('span');
      chip.className = 'wa-chip' + (dep.dev ? ' wa-chip-dev' : '');
      chip.title = (dep.manifest || '') + (dep.version ? ' ' + dep.version : '');
      chip.textContent = dep.name + (dep.version ? ' ' + dep.version : '');
      chipWrap.appendChild(chip);
    });
    depsLane.appendChild(chipWrap);
    archRoot.appendChild(depsLane);
  }

  if (!ARCH.lanes.length && !ARCH.dependencies.length) {
    archRoot.innerHTML = '<div class="wa-empty">No se detectaron módulos ni dependencias.</div>';
  }

  var detailPanel = document.getElementById('wa-detail');
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
    detailPanel.innerHTML = html;
    detailPanel.classList.add('wa-open');
    document.getElementById('wa-detail-close').addEventListener('click', function() {
      detailPanel.classList.remove('wa-open');
    });
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

    sections = [_render_library_html()]
    sections.append(
        '<section id="view-architecture" hidden><div id="wa-architecture-body"></div></section>'
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

    js = (
        _JS
        .replace("__ARCH_DATA__", json.dumps(arch_data, ensure_ascii=False))
        .replace("__SEQ_DATA__", json.dumps(sequences, ensure_ascii=False))
        .replace("__KIND_COLOURS__", json.dumps(_KIND_COLOURS_JS, ensure_ascii=False))
    )

    html = (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        f"<title>WenuRoute — Architecture Library</title>{_CSS}</head><body>"
        '<div id="wa-header"><h1>⚡ WenuRoute — Architecture Library</h1></div>'
        f'<div id="wa-tabs">{"".join(nav_buttons)}</div>'
        f'<main>{"".join(sections)}</main>'
        '<div id="wa-detail"></div>'
        f"{js}"
        "</body></html>"
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
