"""Flutter / Dart parser.

Detects:
- Widget class definitions (StatelessWidget, StatefulWidget)
- Button / GestureDetector / InkWell onPressed / onTap handlers
- Navigator.push / pushNamed → routes
- http.get / http.post / dio calls → endpoints
- Function / method definitions
"""

from __future__ import annotations

import re
from pathlib import Path

from wenuroute.models import NodeKind, RouteEdge, RouteGraph, RouteNode
from wenuroute.parsers.base import BaseParser

_CLASS_DEF = re.compile(
    r"""class\s+(\w+)\s*(?:extends\s+(\w+))?""",
    re.MULTILINE,
)

_METHOD_DEF = re.compile(
    r"""(?:Future|void|Widget|String|int|bool|double|dynamic|List|Map)[\w<>, ?]*\s+(\w+)\s*\(([^)]*)\)""",
    re.MULTILINE,
)

_ON_PRESSED = re.compile(
    r"""on(?:Pressed|Tap|Changed|Submitted)\s*:\s*\(?\s*\)?\s*(?:async\s*)?\{""",
    re.MULTILINE,
)

_NAVIGATOR = re.compile(
    r"""Navigator\s*\.\s*(?:pushNamed|push|pushReplacement)\s*\(\s*\w+\s*,\s*['"]?([^'",)]+)['"]?""",
    re.MULTILINE,
)

_HTTP_CALL = re.compile(
    r"""(?:http|dio)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE | re.MULTILINE,
)


class FlutterParser(BaseParser):
    """Parse Flutter / Dart source files."""

    EXTENSIONS = (".dart",)

    def parse(self, path: Path) -> RouteGraph:
        graph = RouteGraph()
        source = path.read_text(encoding="utf-8", errors="replace")
        rel = self._rel(path)

        module_id = self._node_id(path, rel, 0)
        graph.add_node(RouteNode(id=module_id, label=rel, kind=NodeKind.MODULE, file=rel))

        # Widget / class definitions
        widget_classes = {"StatelessWidget", "StatefulWidget", "State"}
        for m in _CLASS_DEF.finditer(source):
            name = m.group(1)
            parent = m.group(2) or ""
            line = source[: m.start()].count("\n") + 1
            kind = NodeKind.UI_ELEMENT if any(w in parent for w in widget_classes) else NodeKind.FUNCTION
            cls_id = self._node_id(path, name, line)
            graph.add_node(
                RouteNode(
                    id=cls_id,
                    label=name,
                    kind=kind,
                    file=rel,
                    line=line,
                    metadata={"parent": parent},
                )
            )
            graph.add_edge(RouteEdge(module_id, cls_id, "defines"))

        # Method definitions
        for m in _METHOD_DEF.finditer(source):
            name = m.group(1)
            raw_params = m.group(2)
            params = [p.strip().split()[-1] if p.strip() else ""
                      for p in raw_params.split(",") if p.strip()]
            params = [p for p in params if p]
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

        # onPressed / onTap handlers
        for i, m in enumerate(_ON_PRESSED.finditer(source)):
            line = source[: m.start()].count("\n") + 1
            event_id = self._node_id(path, f"handler[{i}]", line)
            label = m.group(0).split(":")[0].strip()
            graph.add_node(
                RouteNode(
                    id=event_id,
                    label=label,
                    kind=NodeKind.EVENT,
                    file=rel,
                    line=line,
                )
            )
            graph.add_edge(RouteEdge(module_id, event_id, "handles"))

        # Navigator calls → routes
        for m in _NAVIGATOR.finditer(source):
            route = m.group(1).strip()
            line = source[: m.start()].count("\n") + 1
            ep_id = f"endpoint:ROUTE:{route}"
            graph.add_node(
                RouteNode(
                    id=ep_id,
                    label=f"navigate {route}",
                    kind=NodeKind.ENDPOINT,
                    file=rel,
                    line=line,
                )
            )
            graph.add_edge(RouteEdge(module_id, ep_id, "navigates"))

        # HTTP calls → endpoints
        for m in _HTTP_CALL.finditer(source):
            method = m.group(1).upper()
            url = m.group(2)
            line = source[: m.start()].count("\n") + 1
            ep_id = f"endpoint:{method}:{url}"
            graph.add_node(
                RouteNode(
                    id=ep_id,
                    label=f"{method} {url}",
                    kind=NodeKind.ENDPOINT,
                    file=rel,
                    line=line,
                    metadata={"method": method},
                )
            )
            graph.add_edge(RouteEdge(module_id, ep_id, "calls"))

        return graph
