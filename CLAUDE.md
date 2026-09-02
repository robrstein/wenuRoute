# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

WenuRoute is a Python CLI tool that statically analyzes a codebase (HTML, React/JS/TS, Python, Node.js/Express, Flutter/Dart, Android Java/Kotlin) and produces an interactive execution-route graph — either an HTML visualization (PyVis/vis.js) or a console text summary — showing how UI elements, functions, endpoints, and SQL/ORM calls connect to each other.

## Build & Test

```bash
# Install in editable mode (required before running anything)
pip install -e .

# Run full test suite
python -m pytest tests/ -v

# Run a single test
python -m pytest tests/test_parsers.py::TestPythonParser::test_detects_flask_route -v

# Run the tool itself
wenuroute ./some-project                # writes wenuroute_graph.html
wenuroute ./some-project --format text  # console summary, no browser
wenuroute ./some-project -o report.html
wenuroute ./some-project --verbose      # print each file as it's parsed
```

Requires Python 3.9+.

## Architecture

**Data flow:**

```
CLI (cli.py)
  └─ Analyzer (analyzer.py)         — walks file tree, dispatches by extension
       └─ BaseParser subclasses      — one per language, each returns a RouteGraph
            └─ models.py             — RouteNode / RouteEdge / RouteGraph
  └─ graph.py                       — renders RouteGraph → HTML (PyVis) or text
```

| File | Role |
|---|---|
| `wenuroute/models.py` | Shared data types: `NodeKind` enum, `RouteNode`, `RouteEdge`, `RouteGraph` |
| `wenuroute/parsers/base.py` | Abstract `BaseParser` — declares `EXTENSIONS`, `parse()`, `_node_id()`, `_rel()` |
| `wenuroute/parsers/__init__.py` | `ALL_PARSERS` list — the registry `Analyzer` uses to discover all parsers |
| `wenuroute/analyzer.py` | Orchestrates traversal; builds an extension→parser index at init time |
| `wenuroute/graph.py` | `render_html()` (PyVis) and `render_console()` renderers |
| `wenuroute/cli.py` | Click entry point (`wenuroute` command) |

## Key conventions

### Adding a new language parser

1. Create `wenuroute/parsers/<lang>.py`, subclass `BaseParser`.
2. Declare `EXTENSIONS: tuple[str, ...] = (".ext",)`.
3. Implement `parse(self, path: Path) -> RouteGraph`.
4. Register it in `parsers/__init__.py` — add to the `ALL_PARSERS` list and `__all__`.

`Analyzer` picks it up automatically from `ALL_PARSERS`; no other changes needed. If the new language targets a project layer not yet covered, also add its extensions to `_LAYER_EXTS` in `graph.py` (see below).

### Node IDs

Node IDs are always `"<relative/path>:line:name"`, generated via `self._node_id(path, name, line)`. Relative paths use POSIX separators via `self._rel(path)`. Use this helper — don't build IDs manually.

### RouteGraph is idempotent

`add_edge()` deduplicates by value equality. `merge()` updates nodes in-place (later wins on collision) and deduplicates edges. Parsers can add the same node/edge multiple times safely.

### Node colors and shapes

Each `NodeKind` (`ui_element`, `function`, `endpoint`, `sql`, `style`, `event`, `module`, `unknown`) maps to a colour and shape in `graph.py` (`_COLOUR`, `_SHAPE` dicts). When adding a new `NodeKind`, extend both dicts and `_KIND_LABELS`.

### Layer auto-detection (`graph.py`)

`_detect_layer(file_path)` maps file extensions to project layers (`frontend`, `backend`, `mobile`, `other`) via rules in `_LAYER_EXTS`. Adding a new language parser targeting a new layer may require adding its extensions there.

### Interactive HTML sidebar & enhancements (`graph.py`)

`render_html()` uses `net.generate_html()` (not `write_html()`) to capture the PyVis HTML as a string, then calls `_inject_enhancements()` which injects three blocks:

- **CSS** (`_SIDEBAR_CSS_TMPL`) — sidebar, context menu, detail panel, minimap styles. Uses `__WIDTH__` (`_SIDEBAR_W = 265`) and `__DETAIL_W__` (`_DETAIL_W = 280`) as string placeholders replaced at render time. Braces in CSS must **not** be escaped because the template is a plain string, not an f-string.
- **Sidebar HTML** (`_build_sidebar_html()`) — left panel with search, layer buttons, kind checkboxes, cluster/fit/physics/minimap controls.
- **JS** (`_ENHANCEMENT_JS_TMPL`) — all interactivity. Uses `__META__` as placeholder for the injected node-metadata JSON (`json.dumps(node_meta)`).

The `META` object embedded in JS contains per-node: `kind`, `layer`, `label`, `file`, `line`, `params`. The vis.js globals `nodes`, `edges`, and `network` (set by PyVis before the injected `<script>` runs) are accessible in all sections of the IIFE.

The JS is a single IIFE with these sections (in order): `Clustering → Filters → Search → Focus mode → Detail panel → Minimap → Toolbar`. All sections share closure variables: `META`, `hiddenKinds`, `hiddenLayers`, `focusIds`, `clustersActive`, `mmEl`, `mmCanvas`, `mmToGraph`.

`updateStats()` always calls `drawMinimap()` at the end — so any filter/focus/cluster change updates both the stats counter and the minimap without extra wiring.

### Minimap (`graph.py`, Minimap section of the injected JS)

`drawMinimap()` uses `network.getPositions()` to get all node coordinates, scales them to fit a 200×140 canvas, draws edges as faint lines and nodes as 2px coloured circles. Cluster nodes (`id.startsWith('wrcluster::')`) are drawn as 3.5px circles in their layer border colour. Hidden nodes are dimmed. The viewport rectangle uses `network.getViewPosition()` + `network.getScale()` + `#mynetwork` dimensions. Clicking the canvas converts pixel → graph coords via the `mmToGraph` closure and calls `network.moveTo()`.

### Analyzer file traversal (`analyzer.py`)

`_collect_files()` walks `project_root.rglob("*")` and skips `_SKIP_DIRS` (`.git`, `node_modules`, `__pycache__`, `.venv`, `build`, `dist`, `.gradle`, `.idea`, `.vscode`, `ios`, etc.). A file is only included if at least one parser claims its extension via the extension→parser index built in `__init__`. Per-file parse errors are caught and reported through `progress_callback` rather than aborting the whole run.

### Parser tests pattern

Each parser test class instantiates the parser with `tmp_path` as the project root, writes a minimal source file, calls `parser.parse(file)`, and asserts on `NodeKind` membership or label content. Follow this pattern for new parser tests.

## Notes

- `wenuroute_graph.html` at the repo root is a generated sample output (WenuRoute run on itself), not hand-maintained source.
- `.github/copilot-instructions.md` mirrors this file for Copilot; keep the two in sync if architecture changes.
