"""Graph visualisation — generates an interactive HTML graph using PyVis."""

from __future__ import annotations

import json
from pathlib import Path

from wenuroute.models import NodeKind, RouteGraph

# --------------------------------------------------------------------------- #
# Colour / shape palettes
# --------------------------------------------------------------------------- #

_COLOUR: dict[NodeKind, str] = {
    NodeKind.UI_ELEMENT: "#4CAF50",   # green
    NodeKind.FUNCTION:   "#2196F3",   # blue
    NodeKind.ENDPOINT:   "#FF9800",   # orange
    NodeKind.SQL:        "#F44336",   # red
    NodeKind.STYLE:      "#9C27B0",   # purple
    NodeKind.EVENT:      "#00BCD4",   # cyan
    NodeKind.MODULE:     "#607D8B",   # grey-blue
    NodeKind.UNKNOWN:    "#9E9E9E",   # grey
}

_SHAPE: dict[NodeKind, str] = {
    NodeKind.UI_ELEMENT: "box",
    NodeKind.FUNCTION:   "ellipse",
    NodeKind.ENDPOINT:   "diamond",
    NodeKind.SQL:        "database",
    NodeKind.STYLE:      "dot",
    NodeKind.EVENT:      "star",
    NodeKind.MODULE:     "square",
    NodeKind.UNKNOWN:    "dot",
}

_TITLE_TMPL = """\
<b>{label}</b><br>
kind: {kind}<br>
file: {file}<br>
line: {line}<br>
params: {params}
"""

# --------------------------------------------------------------------------- #
# Layer auto-detection
# --------------------------------------------------------------------------- #

_LAYER_EXTS: list[tuple[tuple[str, ...], str]] = [
    ((".dart",), "mobile"),
    ((".java", ".kt"), "mobile"),
    ((".py",), "backend"),
    ((".html", ".htm", ".js", ".jsx", ".ts", ".tsx", ".css", ".vue", ".svelte"), "frontend"),
]

_LAYER_META: dict[str, tuple[str, str]] = {
    "frontend": ("🌐", "Frontend"),
    "backend":  ("⚙️", "Backend"),
    "mobile":   ("📱", "Mobile"),
    "other":    ("📦", "Otro"),
}

_KIND_LABELS: dict[str, str] = {
    "ui_element": "UI Element",
    "function":   "Function",
    "endpoint":   "Endpoint",
    "sql":        "SQL",
    "style":      "Style",
    "event":      "Event",
    "module":     "Module",
    "unknown":    "Unknown",
}

_SIDEBAR_W = 265  # sidebar width in px
_DETAIL_W  = 280  # detail panel width in px


def _detect_layer(file_path: str) -> str:
    p = (file_path or "").lower()
    for exts, layer in _LAYER_EXTS:
        if any(p.endswith(ext) for ext in exts):
            return layer
    return "other"


# --------------------------------------------------------------------------- #
# Sidebar HTML + CSS template
# --------------------------------------------------------------------------- #

# Uses __WIDTH__ as placeholder so braces in CSS don't need escaping.
_SIDEBAR_CSS_TMPL = """\
<style id="wr-style">
#wr-panel {
  position: fixed; top: 0; left: 0;
  width: __WIDTH__px; height: 100vh;
  background: #12122a;
  border-right: 1px solid #2a2a5a;
  overflow-y: auto; z-index: 1000;
  padding: 14px 12px; box-sizing: border-box;
  font-family: 'Segoe UI', Arial, sans-serif;
  color: #e0e0e0; font-size: 13px;
}
#mynetwork {
  margin-left: __WIDTH__px !important;
  width: calc(100% - __WIDTH__px) !important;
}
#loadingBar {
  left: __WIDTH__px !important;
  width: calc(100% - __WIDTH__px) !important;
}
#wr-title {
  font-size: 15px; font-weight: 700; color: #7aa2f7;
  margin-bottom: 12px; padding-bottom: 8px;
  border-bottom: 1px solid #2a2a5a;
}
.wr-section { margin-bottom: 14px; }
.wr-section-title {
  font-size: 10px; text-transform: uppercase;
  letter-spacing: 0.9px; color: #6272a4; margin-bottom: 6px;
}
.wr-check-item {
  display: flex; align-items: center; gap: 7px;
  padding: 2px 0; cursor: pointer;
}
.wr-check-item input { cursor: pointer; accent-color: #7aa2f7; }
.wr-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.wr-layer-btn {
  display: block; width: 100%; padding: 5px 9px; margin-bottom: 4px;
  border: 1px solid #3d3d6e; background: #1e1e3f; color: #e0e0e0;
  border-radius: 5px; font-size: 12px; cursor: pointer;
  text-align: left; transition: background 0.12s;
}
.wr-layer-btn.active { background: #2d3a6e; border-color: #7aa2f7; }
.wr-layer-btn:hover { background: #252550; }
#wr-search {
  width: 100%; padding: 6px 9px;
  border: 1px solid #3d3d6e; background: #1e1e3f;
  color: #e0e0e0; border-radius: 5px;
  font-size: 12px; box-sizing: border-box; outline: none;
}
#wr-search:focus { border-color: #7aa2f7; }
#wr-search-info { font-size: 11px; color: #6272a4; margin-top: 4px; min-height: 16px; }
.wr-btn {
  display: block; width: 100%; padding: 6px 9px; margin-bottom: 5px;
  border: 1px solid #3d3d6e; background: #1e1e3f; color: #e0e0e0;
  border-radius: 5px; font-size: 12px; cursor: pointer;
  text-align: left; transition: background 0.12s;
}
.wr-btn:hover { background: #252550; }
#wr-stats {
  font-size: 11px; color: #6272a4;
  padding-top: 10px; border-top: 1px solid #2a2a5a; line-height: 1.7;
}
/* focus mode banner + exit button */
#wr-focus-banner {
  display: none; background: #0d2444;
  border: 1px solid #2196F3; border-radius: 5px;
  padding: 7px 9px; margin-bottom: 6px;
  font-size: 11px; color: #90c8ff; line-height: 1.5;
}
#wr-focus-exit {
  display: none; width: 100%; padding: 5px 9px; margin-bottom: 6px;
  border: 1px solid #2196F3; background: #0d2444; color: #90c8ff;
  border-radius: 5px; font-size: 12px; cursor: pointer;
  text-align: left; box-sizing: border-box; transition: background 0.12s;
}
#wr-focus-exit:hover { background: #1a3a6e; }
/* right-click context menu */
#wr-ctx-menu {
  display: none; position: fixed; z-index: 9999;
  background: #1a1a3a; border: 1px solid #3d3d6e;
  border-radius: 7px; padding: 4px 0; min-width: 210px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.7);
  font-family: 'Segoe UI', Arial, sans-serif;
}
.wr-ctx-title {
  padding: 6px 14px 5px; font-size: 10px; color: #7aa2f7;
  font-weight: 700; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 220px;
  border-bottom: 1px solid #2a2a5a; margin-bottom: 3px;
}
.wr-ctx-item {
  padding: 7px 14px; font-size: 12px; color: #e0e0e0;
  cursor: pointer; white-space: nowrap;
}
.wr-ctx-item:hover { background: #2d3a6e; }
.wr-ctx-separator { height: 1px; background: #2a2a5a; margin: 3px 0; }
/* ── Detail panel ─────────────────────────────────────── */
body.wr-detail-open #mynetwork {
  width: calc(100% - __WIDTH__px - __DETAIL_W__px) !important;
}
#wr-detail {
  position: fixed; top: 0; right: -__DETAIL_W__px;
  width: __DETAIL_W__px; height: 100vh;
  background: #12122a; border-left: 1px solid #2a2a5a;
  overflow-y: auto; z-index: 998; box-sizing: border-box;
  font-family: 'Segoe UI', Arial, sans-serif;
  color: #e0e0e0; font-size: 13px;
  transition: right 0.2s ease;
}
#wr-detail.wr-open { right: 0; }
#wr-det-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 12px 8px; border-bottom: 1px solid #2a2a5a;
  position: sticky; top: 0; background: #12122a; z-index: 1;
}
#wr-det-header-title { font-size: 11px; color: #6272a4; text-transform: uppercase; letter-spacing: 0.8px; }
#wr-det-close { background: none; border: none; color: #6272a4; cursor: pointer; font-size: 18px; padding: 0 2px; line-height: 1; }
#wr-det-close:hover { color: #e0e0e0; }
#wr-det-body { padding: 12px; }
.wr-det-kind-row { display: flex; align-items: center; gap: 7px; margin-bottom: 6px; }
.wr-det-kind { font-size: 10px; text-transform: uppercase; letter-spacing: 0.8px; color: #6272a4; }
.wr-det-name { font-size: 16px; font-weight: 700; color: #e8e8ff; margin-bottom: 12px; word-break: break-word; line-height: 1.3; }
.wr-det-prop { margin-bottom: 8px; }
.wr-det-prop-lbl { font-size: 10px; text-transform: uppercase; letter-spacing: 0.8px; color: #6272a4; margin-bottom: 2px; }
.wr-det-prop-val { font-size: 11px; color: #c0c0d0; word-break: break-all; font-family: 'Consolas', 'Courier New', monospace; background: #1e1e3f; padding: 4px 7px; border-radius: 4px; display: block; }
.wr-det-section-title { font-size: 10px; text-transform: uppercase; letter-spacing: 0.8px; color: #6272a4; margin: 12px 0 5px; padding-top: 10px; border-top: 1px solid #2a2a5a; }
.wr-det-conn { display: flex; align-items: center; gap: 8px; padding: 5px 7px; border-radius: 5px; cursor: pointer; font-size: 12px; color: #c0d0ff; margin-bottom: 2px; border: 1px solid transparent; transition: background 0.1s; }
.wr-det-conn:hover { background: #1e2a4e; border-color: #3d4d7e; }
.wr-det-conn-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }
.wr-det-empty { font-size: 11px; color: #4a4a6a; font-style: italic; padding: 4px 0; }
.wr-det-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; display: inline-block; }
/* ── Minimap ──────────────────────────────────────────── */
#wr-minimap {
  position: fixed; bottom: 14px; right: 14px;
  width: 204px; background: #12122a;
  border: 1px solid #2a2a5a; border-radius: 8px;
  padding: 6px 8px 8px; z-index: 997;
  box-shadow: 0 4px 16px rgba(0,0,0,.55);
  font-family: 'Segoe UI', Arial, sans-serif;
  transition: right 0.2s ease;
}
body.wr-detail-open #wr-minimap { right: calc(__DETAIL_W__px + 14px); }
#wr-minimap-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 5px;
}
#wr-minimap-label { font-size: 10px; color: #6272a4; text-transform: uppercase; letter-spacing: 0.8px; }
#wr-minimap-hide { background: none; border: none; color: #6272a4; cursor: pointer; font-size: 14px; padding: 0 2px; line-height: 1; }
#wr-minimap-hide:hover { color: #e0e0e0; }
#wr-minimap-canvas { display: block; width: 100%; border-radius: 4px; cursor: crosshair; border: 1px solid #1e1e3f; }
</style>"""

# Uses __META__ as placeholder for the injected JSON blob.
_ENHANCEMENT_JS_TMPL = """\
<script id="wr-script">
(function() {
  var META = __META__;
  var hiddenKinds  = new Set();
  var hiddenLayers = new Set();
  var physicsOn    = false;
  var clustersActive = false;
  var focusIds     = null;  // null = full view; plain object used as id→true set
  var ctxTargetNode = null;

  // ── Clustering ────────────────────────────────────────────────────────── //

  var clusterFileMap = {};
  for (var id in META) {
    var file = META[id].file;
    if (!file || file.indexOf('://') !== -1) continue;
    if (!clusterFileMap[file]) clusterFileMap[file] = [];
    clusterFileMap[file].push(id);
  }
  Object.keys(clusterFileMap).forEach(function(f) {
    if (clusterFileMap[f].length < 2) delete clusterFileMap[f];
  });

  var layerBg     = {frontend:'#0d2444', backend:'#0d2a1a', mobile:'#220d44', other:'#1a1a3a'};
  var layerBorder = {frontend:'#2196F3', backend:'#4CAF50', mobile:'#9C27B0', other:'#607D8B'};

  function activateClusters() {
    for (var file in clusterFileMap) {
      var ids   = clusterFileMap[file];
      var layer = (META[ids[0]] || {}).layer || 'other';
      var parts = file.replace(/\\\\/g, '/').split('/');
      var shortName = parts[parts.length - 1];
      network.cluster({
        joinCondition: (function(fIds) {
          return function(n) { return fIds.indexOf(n.id) !== -1; };
        })(ids),
        clusterNodeProperties: {
          id: 'wrcluster::' + file,
          label: shortName + ' (' + ids.length + ')',
          shape: 'square', borderDashes: [6, 3], borderWidth: 2,
          color: {
            background: layerBg[layer]     || layerBg.other,
            border:     layerBorder[layer] || layerBorder.other,
            highlight:  {background: '#2a2a6a', border: '#aaaaff'}
          },
          size: Math.min(20 + ids.length * 2, 42),
          font: {color: '#e0e0e0', size: 12, bold: true},
          title: '<b>' + file + '</b><br>' + ids.length + ' nodos<br><i>doble clic para expandir</i>'
        }
      });
    }
    clustersActive = true;
    document.getElementById('wr-cluster-btn').textContent = '📂 Desagrupar todo';
    updateStats();
  }

  function deactivateClusters() {
    for (var limit = 300; limit > 0; limit--) {
      var found = false;
      nodes.getIds().forEach(function(nid) {
        if (network.isCluster(nid)) { network.openCluster(nid); found = true; }
      });
      if (!found) break;
    }
    clustersActive = false;
    document.getElementById('wr-cluster-btn').textContent = '📁 Agrupar por módulo';
    updateStats();
  }

  network.on('doubleClick', function(params) {
    if (params.nodes.length === 1 && network.isCluster(params.nodes[0])) {
      network.openCluster(params.nodes[0]);
      if (!nodes.getIds().some(function(nid) { return network.isCluster(nid); })) {
        clustersActive = false;
        document.getElementById('wr-cluster-btn').textContent = '📁 Agrupar por módulo';
      }
      updateStats();
    }
  });

  document.getElementById('wr-cluster-btn').addEventListener('click', function() {
    if (clustersActive) deactivateClusters();
    else activateClusters();
    network.fit({animation: {duration: 500, easingFunction: 'easeInOutQuad'}});
  });

  // ── Filters ───────────────────────────────────────────────────────────── //

  function applyFilters() {
    var updates = [];
    for (var id in META) {
      var m = META[id];
      var hide = hiddenKinds.has(m.kind) || hiddenLayers.has(m.layer);
      if (focusIds !== null && !focusIds[id]) hide = true;
      updates.push({id: id, hidden: hide});
    }
    nodes.update(updates);
    updateStats();
  }

  function updateStats() {
    var total = Object.keys(META).length, visible = 0;
    for (var id in META) {
      var m = META[id];
      if (hiddenKinds.has(m.kind) || hiddenLayers.has(m.layer)) continue;
      if (focusIds !== null && !focusIds[id]) continue;
      visible++;
    }
    var totalFiles   = Object.keys(clusterFileMap).length;
    var openClusters = nodes.getIds().filter(function(nid) { return network.isCluster(nid); }).length;
    var el = document.getElementById('wr-stats');
    if (!el) return;
    var html = 'Nodos: <b>' + visible + '</b> / ' + total;
    if (clustersActive)    html += '<br>Clusters: <b>' + openClusters + '</b> / ' + totalFiles;
    if (focusIds !== null) html += '<br>En foco: <b>' + Object.keys(focusIds).length + '</b> nodos';
    el.innerHTML = html;
    drawMinimap();
  }

  document.querySelectorAll('input[data-kind]').forEach(function(cb) {
    cb.addEventListener('change', function() {
      if (this.checked) hiddenKinds.delete(this.dataset.kind);
      else hiddenKinds.add(this.dataset.kind);
      applyFilters();
    });
  });

  document.querySelectorAll('.wr-layer-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var layer = this.dataset.layer;
      if (hiddenLayers.has(layer)) { hiddenLayers.delete(layer); this.classList.add('active'); }
      else { hiddenLayers.add(layer); this.classList.remove('active'); }
      applyFilters();
    });
  });

  // ── Search ────────────────────────────────────────────────────────────── //

  var searchInput = document.getElementById('wr-search');
  var searchInfo  = document.getElementById('wr-search-info');
  searchInput.addEventListener('input', function() {
    var q = this.value.trim().toLowerCase();
    network.unselectAll();
    if (!q) { searchInfo.textContent = ''; return; }
    var matches = [];
    for (var id in META) {
      var m = META[id];
      if (m.label.toLowerCase().indexOf(q) !== -1 || id.toLowerCase().indexOf(q) !== -1)
        matches.push(id);
    }
    searchInfo.textContent = matches.length + ' resultado(s)';
    if (matches.length > 0) {
      network.selectNodes(matches);
      if (matches.length <= 40)
        network.fit({nodes: matches, animation: {duration: 400, easingFunction: 'easeInOutQuad'}});
    }
  });

  // ── Focus mode (ego network) ──────────────────────────────────────────── //

  // BFS up to `depth` hops; returns plain object used as id→true lookup
  function buildEgoNetwork(startId, depth) {
    var visited  = {};
    visited[startId] = true;
    var frontier = [startId];
    for (var d = 0; d < depth; d++) {
      var next = [];
      frontier.forEach(function(nid) {
        network.getConnectedNodes(nid).forEach(function(cid) {
          if (!visited[cid]) { visited[cid] = true; next.push(cid); }
        });
      });
      if (next.length === 0) break;
      frontier = next;
    }
    return visited;
  }

  function enterFocus(nodeId, depth) {
    focusIds = buildEgoNetwork(nodeId, depth);
    applyFilters();
    var label  = META[nodeId] ? META[nodeId].label : nodeId;
    var count  = Object.keys(focusIds).length;
    var banner = document.getElementById('wr-focus-banner');
    banner.innerHTML = '🎯 <b>' + label + '</b><br>'
      + count + ' nodo' + (count !== 1 ? 's' : '')
      + ' · ' + depth + ' nivel' + (depth > 1 ? 'es' : '');
    banner.style.display = 'block';
    document.getElementById('wr-focus-exit').style.display = 'block';
    var ids = Object.keys(focusIds);
    if (ids.length > 0 && ids.length <= 120)
      network.fit({nodes: ids, animation: {duration: 400, easingFunction: 'easeInOutQuad'}});
  }

  function exitFocus() {
    focusIds = null;
    applyFilters();
    document.getElementById('wr-focus-banner').style.display = 'none';
    document.getElementById('wr-focus-exit').style.display   = 'none';
  }

  document.getElementById('wr-focus-exit').addEventListener('click', exitFocus);

  // Context menu — created via JS so no extra HTML injection is needed
  var ctxMenu = document.createElement('div');
  ctxMenu.id = 'wr-ctx-menu';
  ctxMenu.innerHTML =
    '<div class="wr-ctx-title"  id="wr-ctx-label"></div>'  +
    '<div class="wr-ctx-item"   id="wr-ctx-f1">🎯 Ver vecinos directos (1 nivel)</div>'    +
    '<div class="wr-ctx-item"   id="wr-ctx-f2">🔭 Ampliar a 2 niveles de profundidad</div>' +
    '<div class="wr-ctx-separator" id="wr-ctx-sep"></div>'  +
    '<div class="wr-ctx-item"   id="wr-ctx-expand">📂 Expandir cluster</div>';
  document.body.appendChild(ctxMenu);

  function positionAndShow(e, nodeId) {
    ctxTargetNode = nodeId;
    var isCluster = network.isCluster(nodeId);
    var label = isCluster
      ? nodeId.replace('wrcluster::', '')
      : (META[nodeId] ? META[nodeId].label : nodeId);
    document.getElementById('wr-ctx-label').textContent   = label;
    document.getElementById('wr-ctx-f1').style.display      = isCluster ? 'none' : 'block';
    document.getElementById('wr-ctx-f2').style.display      = isCluster ? 'none' : 'block';
    document.getElementById('wr-ctx-sep').style.display     = isCluster ? 'none' : 'block';
    document.getElementById('wr-ctx-expand').style.display  = isCluster ? 'block' : 'none';
    ctxMenu.style.display = 'block';
    // Keep within viewport
    var x = e.clientX, y = e.clientY;
    var w = ctxMenu.offsetWidth, h = ctxMenu.offsetHeight;
    if (x + w > window.innerWidth)  x = window.innerWidth  - w - 8;
    if (y + h > window.innerHeight) y = window.innerHeight - h - 8;
    ctxMenu.style.left = x + 'px';
    ctxMenu.style.top  = y + 'px';
  }

  document.getElementById('mynetwork').addEventListener('contextmenu', function(e) {
    e.preventDefault();
    var rect   = this.getBoundingClientRect();
    var nodeId = network.getNodeAt({x: e.clientX - rect.left, y: e.clientY - rect.top});
    if (!nodeId) { ctxMenu.style.display = 'none'; return; }
    positionAndShow(e, nodeId);
  });

  document.getElementById('wr-ctx-f1').addEventListener('click', function() {
    if (ctxTargetNode) enterFocus(ctxTargetNode, 1);
    ctxMenu.style.display = 'none';
  });
  document.getElementById('wr-ctx-f2').addEventListener('click', function() {
    if (ctxTargetNode) enterFocus(ctxTargetNode, 2);
    ctxMenu.style.display = 'none';
  });
  document.getElementById('wr-ctx-expand').addEventListener('click', function() {
    if (ctxTargetNode && network.isCluster(ctxTargetNode)) network.openCluster(ctxTargetNode);
    ctxMenu.style.display = 'none';
  });
  // Dismiss on any outside click
  document.addEventListener('click', function(e) {
    if (!ctxMenu.contains(e.target)) ctxMenu.style.display = 'none';
  });

  // ── Toolbar ───────────────────────────────────────────────────────────── //

  document.getElementById('wr-fit-btn').addEventListener('click', function() {
    network.fit({animation: {duration: 400, easingFunction: 'easeInOutQuad'}});
  });

  var physicsBtn = document.getElementById('wr-physics-btn');
  physicsBtn.addEventListener('click', function() {
    physicsOn = !physicsOn;
    network.setOptions({physics: {enabled: physicsOn}});
    this.textContent = physicsOn ? '⏸ Pausar física' : '▶ Activar física';
  });

  network.once('stabilized', function() {
    setTimeout(function() {
      network.setOptions({physics: {enabled: false}});
      physicsOn = false;
    }, 400);
  });

  // ── Detail panel (replaces floating tooltip) ──────────────────────────── //

  var kindColors = {
    ui_element:'#4CAF50', function:'#2196F3', endpoint:'#FF9800',
    sql:'#F44336', style:'#9C27B0', event:'#00BCD4', module:'#607D8B', unknown:'#9E9E9E'
  };

  var detPanel = document.createElement('div');
  detPanel.id = 'wr-detail';
  detPanel.innerHTML =
    '<div id="wr-det-header">' +
      '<span id="wr-det-header-title">Detalle del nodo</span>' +
      '<button id="wr-det-close" title="Cerrar">\u2715</button>' +
    '</div>' +
    '<div id="wr-det-body"></div>';
  document.body.appendChild(detPanel);

  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function openDetail() {
    document.getElementById('wr-detail').classList.add('wr-open');
    document.body.classList.add('wr-detail-open');
  }
  function closeDetail() {
    document.getElementById('wr-detail').classList.remove('wr-open');
    document.body.classList.remove('wr-detail-open');
  }

  document.getElementById('wr-det-close').addEventListener('click', closeDetail);

  function connItemHtml(nid) {
    var nm = META[nid]; if (!nm) return '';
    return '<div class="wr-det-conn" data-nid="' + escHtml(nid) + '">' +
      '<span class="wr-det-dot" style="background:' + (kindColors[nm.kind] || '#9E9E9E') + '"></span>' +
      '<span class="wr-det-conn-label">' + escHtml(nm.label) + '</span>' +
      '</div>';
  }

  function showNodeDetail(nodeId) {
    var body = document.getElementById('wr-det-body');
    var html = '';

    if (network.isCluster(nodeId)) {
      var file = nodeId.replace('wrcluster::', '');
      var cIds = clusterFileMap[file] || [];
      html += '<div class="wr-det-kind-row"><span class="wr-det-dot" style="background:#607D8B"></span>' +
              '<span class="wr-det-kind">CLUSTER</span></div>';
      html += '<div class="wr-det-name">' + escHtml(file.split('/').pop()) + '</div>';
      html += '<div class="wr-det-prop"><div class="wr-det-prop-lbl">Archivo</div>' +
              '<div class="wr-det-prop-val">' + escHtml(file) + '</div></div>';
      html += '<div class="wr-det-section-title">Contenido (' + cIds.length + ' nodos)</div>';
      html += cIds.map(function(nid) {
        var nm = META[nid]; if (!nm) return '';
        return '<div class="wr-det-conn"><span class="wr-det-dot" style="background:' +
          (kindColors[nm.kind]||'#9E9E9E') + '"></span>' +
          '<span class="wr-det-conn-label">' + escHtml(nm.label) + '</span></div>';
      }).join('');
      body.innerHTML = html;
      openDetail();
      return;
    }

    var m = META[nodeId]; if (!m) return;
    var c = kindColors[m.kind] || '#9E9E9E';
    var inNodes  = network.getConnectedNodes(nodeId, 'from');
    var outNodes = network.getConnectedNodes(nodeId, 'to');

    html += '<div class="wr-det-kind-row">' +
            '<span class="wr-det-dot" style="background:' + c + '"></span>' +
            '<span class="wr-det-kind">' + escHtml(m.kind || '').toUpperCase() + '</span>' +
            '</div>';
    html += '<div class="wr-det-name">' + escHtml(m.label) + '</div>';

    if (m.file) {
      html += '<div class="wr-det-prop"><div class="wr-det-prop-lbl">Archivo</div>' +
              '<div class="wr-det-prop-val">' + escHtml(m.file) + '</div></div>';
    }
    if (m.line) {
      html += '<div class="wr-det-prop"><div class="wr-det-prop-lbl">L\u00ednea</div>' +
              '<div class="wr-det-prop-val">' + escHtml(m.line) + '</div></div>';
    }
    if (m.params && m.params.length > 0) {
      html += '<div class="wr-det-prop"><div class="wr-det-prop-lbl">Par\u00e1metros</div>' +
              '<div class="wr-det-prop-val">' + escHtml(m.params.join(', ')) + '</div></div>';
    }

    if (inNodes.length > 0) {
      html += '<div class="wr-det-section-title">\u2190 Llamado por (' + inNodes.length + ')</div>';
      html += inNodes.map(connItemHtml).join('');
    }
    if (outNodes.length > 0) {
      html += '<div class="wr-det-section-title">\u2192 Llama a / conecta con (' + outNodes.length + ')</div>';
      html += outNodes.map(connItemHtml).join('');
    }
    if (!inNodes.length && !outNodes.length) {
      html += '<div class="wr-det-section-title">Conexiones</div>' +
              '<div class="wr-det-empty">Sin conexiones detectadas</div>';
    }

    body.innerHTML = html;

    // Click on a connected node → navigate to it and show its detail
    body.querySelectorAll('.wr-det-conn[data-nid]').forEach(function(el) {
      el.addEventListener('click', function() {
        var nid = this.dataset.nid;
        network.selectNodes([nid]);
        network.focus(nid, {scale: 1.2, animation: {duration: 300, easingFunction: 'easeInOutQuad'}});
        showNodeDetail(nid);
      });
    });

    openDetail();
  }

  // Click on a node → open detail panel; click on empty canvas → close it
  network.on('click', function(params) {
    if (params.nodes.length === 1) showNodeDetail(params.nodes[0]);
    else if (params.nodes.length === 0 && params.edges.length === 0) closeDetail();
  });

  // Disable floating tooltips — the panel replaces them
  network.setOptions({interaction: {tooltipDelay: 99999}});

  // ── Minimap ───────────────────────────────────────────────────────────── //

  var MM_W = 200, MM_H = 140;
  var mmEl = document.createElement('div');
  mmEl.id = 'wr-minimap';
  mmEl.innerHTML =
    '<div id="wr-minimap-header">' +
      '<span id="wr-minimap-label">\U0001F5FA Vista general</span>' +
      '<button id="wr-minimap-hide" title="Ocultar">\u2715</button>' +
    '</div>' +
    '<canvas id="wr-minimap-canvas" width="' + MM_W + '" height="' + MM_H + '"></canvas>';
  document.body.appendChild(mmEl);

  var mmCanvas = document.getElementById('wr-minimap-canvas');
  var mmCtx    = mmCanvas.getContext('2d');
  var mmToGraph = null;

  function drawMinimap() {
    if (mmEl.style.display === 'none') return;
    var positions = network.getPositions();
    var ids = Object.keys(positions);
    mmCtx.clearRect(0, 0, MM_W, MM_H);
    mmCtx.fillStyle = '#0d0d1a';
    mmCtx.fillRect(0, 0, MM_W, MM_H);
    if (!ids.length) return;

    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    ids.forEach(function(id) {
      var p = positions[id];
      if (p.x < minX) minX = p.x; if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y; if (p.y > maxY) maxY = p.y;
    });
    var pad = 12, rX = (maxX - minX) || 1, rY = (maxY - minY) || 1;
    var sc = Math.min((MM_W - pad*2) / rX, (MM_H - pad*2) / rY);
    var ox = pad + (MM_W - pad*2 - rX*sc) / 2;
    var oy = pad + (MM_H - pad*2 - rY*sc) / 2;

    function toMM(x, y) { return {x: ox + (x-minX)*sc, y: oy + (y-minY)*sc}; }
    mmToGraph = function(mx, my) { return {x: minX + (mx-ox)/sc, y: minY + (my-oy)/sc}; };

    // Edges
    mmCtx.strokeStyle = 'rgba(85,85,119,0.35)';
    mmCtx.lineWidth = 0.5;
    edges.get().forEach(function(e) {
      var f = positions[e.from], t = positions[e.to];
      if (!f || !t) return;
      var fm = toMM(f.x, f.y), tm = toMM(t.x, t.y);
      mmCtx.beginPath(); mmCtx.moveTo(fm.x, fm.y); mmCtx.lineTo(tm.x, tm.y); mmCtx.stroke();
    });

    // Nodes (cluster nodes get their layer border colour; regular nodes get kind colour)
    ids.forEach(function(id) {
      var p = positions[id], mm = toMM(p.x, p.y), m = META[id];
      var isCluster = id.indexOf('wrcluster::') === 0;
      var color;
      if (isCluster) {
        var file0 = id.replace('wrcluster::', '');
        var fid0  = (clusterFileMap[file0] || [])[0];
        var layer0 = fid0 && META[fid0] ? META[fid0].layer : 'other';
        color = layerBorder[layer0] || '#607D8B';
      } else {
        color = m ? (kindColors[m.kind] || '#9E9E9E') : '#9E9E9E';
      }
      var hidden = !isCluster && m &&
        (hiddenKinds.has(m.kind) || hiddenLayers.has(m.layer) ||
         (focusIds !== null && !focusIds[id]));
      mmCtx.fillStyle = hidden ? 'rgba(80,80,80,0.3)' : color;
      mmCtx.beginPath();
      mmCtx.arc(mm.x, mm.y, isCluster ? 3.5 : (hidden ? 1.2 : 2), 0, Math.PI * 2);
      mmCtx.fill();
    });

    // Viewport rectangle
    var vc = network.getViewPosition(), vs = network.getScale();
    var netDiv = document.getElementById('mynetwork');
    var vpW = netDiv.offsetWidth / vs, vpH = netDiv.offsetHeight / vs;
    var tl = toMM(vc.x - vpW/2, vc.y - vpH/2), br = toMM(vc.x + vpW/2, vc.y + vpH/2);
    mmCtx.fillStyle = 'rgba(100,120,200,0.12)';
    mmCtx.fillRect(tl.x, tl.y, br.x - tl.x, br.y - tl.y);
    mmCtx.strokeStyle = 'rgba(170,180,255,0.75)';
    mmCtx.lineWidth = 1;
    mmCtx.strokeRect(tl.x, tl.y, br.x - tl.x, br.y - tl.y);
  }

  function setMinimapVisible(visible) {
    mmEl.style.display = visible ? '' : 'none';
    var btn = document.getElementById('wr-minimap-btn');
    if (btn) btn.textContent = visible ? '\U0001F5FA Ocultar minimapa' : '\U0001F5FA Mostrar minimapa';
    if (visible) drawMinimap();
  }

  mmCanvas.addEventListener('click', function(e) {
    if (!mmToGraph) return;
    var rect = mmCanvas.getBoundingClientRect();
    var gp = mmToGraph(
      (e.clientX - rect.left) * (MM_W / rect.width),
      (e.clientY - rect.top)  * (MM_H / rect.height)
    );
    network.moveTo({position: gp, animation: {duration: 250, easingFunction: 'easeInOutQuad'}});
  });

  document.getElementById('wr-minimap-hide').addEventListener('click', function() {
    setMinimapVisible(false);
  });
  document.getElementById('wr-minimap-btn').addEventListener('click', function() {
    setMinimapVisible(mmEl.style.display === 'none');
  });

  network.on('zoom',              drawMinimap);
  network.on('dragEnd',           drawMinimap);
  network.on('animationFinished', drawMinimap);
  network.on('stabilized',        drawMinimap);

  updateStats();
})();
</script>"""


def _build_sidebar_html(
    node_meta: dict[str, dict],
    colour_by_kind: dict[str, str],
) -> str:
    kinds   = sorted({v["kind"]  for v in node_meta.values()})
    layers  = sorted({v["layer"] for v in node_meta.values()})

    kind_items = "".join(
        '<label class="wr-check-item">'
        f'<input type="checkbox" checked data-kind="{k}">'
        f'<span class="wr-dot" style="background:{colour_by_kind.get(k, "#9E9E9E")}"></span>'
        f'<span>{_KIND_LABELS.get(k, k)}</span>'
        "</label>"
        for k in kinds
    )
    layer_btns = "".join(
        f'<button class="wr-layer-btn active" data-layer="{la}">'
        f'{_LAYER_META.get(la, ("📦", la))[0]} {_LAYER_META.get(la, ("📦", la))[1]}'
        "</button>"
        for la in layers
    )

    return (
        '<div id="wr-panel">'
        '<div id="wr-title">⚡ WenuRoute</div>'

        '<div class="wr-section">'
        '<div class="wr-section-title">Buscar nodo</div>'
        '<input type="text" id="wr-search" placeholder="nombre o archivo…">'
        '<div id="wr-search-info"></div>'
        "</div>"

        '<div class="wr-section">'
        '<div class="wr-section-title">Capa del proyecto</div>'
        f"{layer_btns}"
        "</div>"

        '<div class="wr-section">'
        '<div class="wr-section-title">Tipo de nodo</div>'
        f"{kind_items}"
        "</div>"

        '<div class="wr-section">'
        '<button class="wr-btn" id="wr-cluster-btn">📁 Agrupar por módulo</button>'
        '<button class="wr-btn" id="wr-fit-btn">⊞ Encuadrar todo</button>'
        '<button class="wr-btn" id="wr-physics-btn">▶ Activar física</button>'
        '<button class="wr-btn" id="wr-minimap-btn">🗺 Ocultar minimapa</button>'
        "</div>"

        '<div id="wr-focus-banner"></div>'
        '<button id="wr-focus-exit">↩ Salir del modo foco</button>'
        '<div id="wr-stats"></div>'
        "</div>"
    )


def _inject_enhancements(
    html: str,
    node_meta: dict[str, dict],
    colour_by_kind: dict[str, str],
) -> str:
    sidebar_html = _build_sidebar_html(node_meta, colour_by_kind)
    css_block    = (
        _SIDEBAR_CSS_TMPL
        .replace("__WIDTH__",    str(_SIDEBAR_W))
        .replace("__DETAIL_W__", str(_DETAIL_W))
    )
    js_block     = _ENHANCEMENT_JS_TMPL.replace(
        "__META__", json.dumps(node_meta, ensure_ascii=False)
    )

    html = html.replace("</head>", f"{css_block}\n</head>", 1)
    html = html.replace('<div id="mynetwork"', f"{sidebar_html}\n<div id=\"mynetwork\"", 1)
    html = html.replace("</body>", f"{js_block}\n</body>", 1)
    return html


# --------------------------------------------------------------------------- #
# Public renderers
# --------------------------------------------------------------------------- #

def render_html(graph: RouteGraph, output: Path) -> None:
    """Render *graph* as an interactive HTML file at *output*."""
    try:
        from pyvis.network import Network  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "pyvis is required for HTML output. Install it with: pip install pyvis"
        ) from exc

    net = Network(
        height="100vh",
        width="100%",
        bgcolor="#1a1a2e",
        font_color="#e0e0e0",
        directed=True,
        notebook=False,
    )

    net.set_options("""
    {
      "physics": {
        "enabled": true,
        "solver": "forceAtlas2Based",
        "forceAtlas2Based": {
          "gravitationalConstant": -80,
          "centralGravity": 0.01,
          "springLength": 120,
          "springConstant": 0.08
        },
        "stabilization": { "iterations": 150 }
      },
      "interaction": {
        "hover": true,
        "navigationButtons": true,
        "tooltipDelay": 100
      },
      "edges": {
        "arrows": { "to": { "enabled": true, "scaleFactor": 0.6 } },
        "color": { "color": "#555577", "highlight": "#aaaaff" },
        "font": { "size": 9, "color": "#888888" },
        "smooth": { "type": "dynamic" }
      }
    }
    """)

    for node in graph.nodes.values():
        colour = _COLOUR.get(node.kind, _COLOUR[NodeKind.UNKNOWN])
        shape = _SHAPE.get(node.kind, "dot")
        title = _TITLE_TMPL.format(
            label=node.label,
            kind=node.kind.value,
            file=node.file or "—",
            line=node.line or "—",
            params=", ".join(node.params) if node.params else "—",
        )
        net.add_node(
            node.id,
            label=node.label[:40],
            title=title,
            color=colour,
            shape=shape,
            size=18 if node.kind == NodeKind.MODULE else 12,
        )

    for edge in graph.edges:
        if edge.source_id in graph.nodes and edge.target_id in graph.nodes:
            net.add_edge(edge.source_id, edge.target_id, title=edge.label, label=edge.label)

    output.parent.mkdir(parents=True, exist_ok=True)

    node_meta = {
        node.id: {
            "kind":   node.kind.value,
            "layer":  _detect_layer(node.file),
            "label":  node.label,
            "file":   node.file,
            "line":   node.line,
            "params": node.params,
        }
        for node in graph.nodes.values()
    }
    colour_by_kind = {k.value: v for k, v in _COLOUR.items()}

    html_str = net.generate_html()
    html_str = _inject_enhancements(html_str, node_meta, colour_by_kind)
    output.write_text(html_str, encoding="utf-8")


def render_console(graph: RouteGraph) -> str:
    """Return a plain-text summary of the graph (for --format text)."""
    lines: list[str] = []
    lines.append(f"Nodes: {len(graph.nodes)}  Edges: {len(graph.edges)}\n")

    by_kind: dict[NodeKind, list] = {}
    for node in graph.nodes.values():
        by_kind.setdefault(node.kind, []).append(node)

    order = [
        NodeKind.MODULE,
        NodeKind.UI_ELEMENT,
        NodeKind.EVENT,
        NodeKind.FUNCTION,
        NodeKind.ENDPOINT,
        NodeKind.SQL,
        NodeKind.STYLE,
        NodeKind.UNKNOWN,
    ]

    for kind in order:
        nodes = by_kind.get(kind, [])
        if not nodes:
            continue
        lines.append(f"── {kind.value.upper()} ({len(nodes)}) ──")
        for node in sorted(nodes, key=lambda n: (n.file, n.line)):
            param_str = f"({', '.join(node.params)})" if node.params else ""
            loc = f"{node.file}:{node.line}" if node.file else ""
            lines.append(f"   {node.label}{param_str}  [{loc}]")
        lines.append("")

    return "\n".join(lines)
