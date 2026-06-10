"""React / JavaScript / TypeScript parser.

Detects:
- React component definitions (function/class components)
- JSX elements with event handlers (onClick, onChange, …)
- fetch() / axios calls → endpoints
- Function definitions and their parameters
- import / require statements
"""

from __future__ import annotations

import re
from pathlib import Path

from wenuroute.models import NodeKind, RouteEdge, RouteGraph, RouteNode
from wenuroute.parsers.base import BaseParser

# --- patterns ---------------------------------------------------------------

_IMPORT = re.compile(
    r"""(?:import\s+.*?\s+from\s+['"](.+?)['"]|require\s*\(\s*['"](.+?)['"]\s*\))""",
    re.MULTILINE,
)

_FUNCTION_DEF = re.compile(
    r"""(?:function\s+(\w+)\s*\(([^)]*)\)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>)""",
    re.MULTILINE,
)

_CLASS_DEF = re.compile(r"class\s+(\w+)\s*(?:extends\s+\w+)?\s*\{", re.MULTILINE)

_JSX_EVENT = re.compile(
    r"""on[A-Z]\w+\s*=\s*\{([^}]+)\}""",
    re.MULTILINE,
)

_FETCH_CALL = re.compile(
    r"""fetch\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.MULTILINE,
)

_AXIOS_CALL = re.compile(
    r"""axios\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE | re.MULTILINE,
)

_FUNC_CALL = re.compile(r"(\w[\w.]*)\s*\(([^)]*)\)")

_ROUTE_ATTR = re.compile(
    r"""(?:path|to|href)\s*=\s*['"`]([^'"`]+)['"`]""",
    re.MULTILINE,
)


class ReactParser(BaseParser):
    """Parse React/JSX/TSX/JS/TS files."""

    EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")

    def parse(self, path: Path) -> RouteGraph:
        graph = RouteGraph()
        source = path.read_text(encoding="utf-8", errors="replace")
        rel = self._rel(path)
        lines = source.splitlines()

        # Module node
        module_id = self._node_id(path, rel, 0)
        graph.add_node(RouteNode(id=module_id, label=rel, kind=NodeKind.MODULE, file=rel))

        # Imports
        for m in _IMPORT.finditer(source):
            imported = m.group(1) or m.group(2)
            imp_id = f"import:{imported}"
            graph.add_node(
                RouteNode(id=imp_id, label=imported, kind=NodeKind.MODULE, file=imported)
            )
            graph.add_edge(RouteEdge(module_id, imp_id, "imports"))

        # Class components
        for m in _CLASS_DEF.finditer(source):
            name = m.group(1)
            line = source[: m.start()].count("\n") + 1
            comp_id = self._node_id(path, name, line)
            graph.add_node(
                RouteNode(
                    id=comp_id, label=name, kind=NodeKind.FUNCTION, file=rel, line=line
                )
            )
            graph.add_edge(RouteEdge(module_id, comp_id, "defines"))

        # Function / arrow-function definitions
        for m in _FUNCTION_DEF.finditer(source):
            name = m.group(1) or m.group(3)
            raw_params = m.group(2) if m.group(2) is not None else (m.group(4) or "")
            params = [p.strip().lstrip("...").split("=")[0].strip()
                      for p in raw_params.split(",") if p.strip()]
            line = source[: m.start()].count("\n") + 1
            fn_id = self._node_id(path, name, line)
            graph.add_node(
                RouteNode(
                    id=fn_id,
                    label=name,
                    kind=NodeKind.FUNCTION,
                    file=rel,
                    line=line,
                    params=params,
                )
            )
            graph.add_edge(RouteEdge(module_id, fn_id, "defines"))

        # JSX event handlers
        for m in _JSX_EVENT.finditer(source):
            handler_expr = m.group(1).strip()
            line = source[: m.start()].count("\n") + 1
            event_id = self._node_id(path, f"event:{handler_expr[:30]}", line)
            graph.add_node(
                RouteNode(
                    id=event_id,
                    label=handler_expr[:60],
                    kind=NodeKind.EVENT,
                    file=rel,
                    line=line,
                )
            )
            graph.add_edge(RouteEdge(module_id, event_id, "handles"))

        # fetch() calls → endpoints
        for m in _FETCH_CALL.finditer(source):
            url = m.group(1)
            line = source[: m.start()].count("\n") + 1
            ep_id = f"endpoint:GET:{url}"
            graph.add_node(
                RouteNode(
                    id=ep_id,
                    label=f"fetch {url}",
                    kind=NodeKind.ENDPOINT,
                    file=rel,
                    line=line,
                )
            )
            graph.add_edge(RouteEdge(module_id, ep_id, "calls"))

        # axios calls → endpoints
        for m in _AXIOS_CALL.finditer(source):
            method = m.group(1).upper()
            url = m.group(2)
            line = source[: m.start()].count("\n") + 1
            ep_id = f"endpoint:{method}:{url}"
            graph.add_node(
                RouteNode(
                    id=ep_id,
                    label=f"axios.{method} {url}",
                    kind=NodeKind.ENDPOINT,
                    file=rel,
                    line=line,
                    metadata={"method": method},
                )
            )
            graph.add_edge(RouteEdge(module_id, ep_id, "calls"))

        # React Router <Route path="..."> / <Link to="..."> / href="..."
        for m in _ROUTE_ATTR.finditer(source):
            url = m.group(1)
            if url.startswith("/") or url.startswith("http"):
                line = source[: m.start()].count("\n") + 1
                ep_id = f"endpoint:ROUTE:{url}"
                graph.add_node(
                    RouteNode(
                        id=ep_id,
                        label=f"route {url}",
                        kind=NodeKind.ENDPOINT,
                        file=rel,
                        line=line,
                    )
                )
                graph.add_edge(RouteEdge(module_id, ep_id, "navigates"))

        return graph
