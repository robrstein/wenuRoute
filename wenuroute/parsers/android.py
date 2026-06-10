"""Android parser (Java & Kotlin).

Detects:
- Activity / Fragment class definitions
- onClick listeners / setOnClickListener lambdas
- Intent navigation
- Retrofit / OkHttp / Volley HTTP calls → endpoints
- Room / SQLiteDatabase queries → SQL nodes
- Method definitions
"""

from __future__ import annotations

import re
from pathlib import Path

from wenuroute.models import NodeKind, RouteEdge, RouteGraph, RouteNode
from wenuroute.parsers.base import BaseParser

# Java / Kotlin class
_CLASS_DEF = re.compile(
    r"""(?:class|interface|object)\s+(\w+)(?:\s*:\s*(\w+)|\s+extends\s+(\w+)|\s+implements\s+(\w+))?""",
    re.MULTILINE,
)

# Java method
_JAVA_METHOD = re.compile(
    r"""(?:public|private|protected|override|fun|void|static)[\w\s<>,?[\]]*\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+[\w,\s]+)?\s*\{""",
    re.MULTILINE,
)

# setOnClickListener
_ONCLICK = re.compile(
    r"""setOnClickListener\s*\{|setOnClickListener\s*\(\s*(?:new\s+\w+|this|\w+)""",
    re.MULTILINE,
)

# Intent start
_INTENT = re.compile(
    r"""(?:Intent|startActivity|startFragment)\s*\(\s*(?:this\s*,\s*)?(\w+)""",
    re.MULTILINE,
)

# Retrofit interface method annotations
_RETROFIT = re.compile(
    r"""@(GET|POST|PUT|DELETE|PATCH)\s*\(\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# OkHttp / Volley
_OKHTTP = re.compile(
    r"""\.(?:url|newCall)\s*\(\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# Room / SQLite
_ROOM_QUERY = re.compile(
    r"""@Query\s*\(\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_SQLITE_EXEC = re.compile(
    r"""(?:execSQL|rawQuery)\s*\(\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)


class AndroidParser(BaseParser):
    """Parse Android Java/Kotlin source files."""

    EXTENSIONS = (".java", ".kt")

    def parse(self, path: Path) -> RouteGraph:
        graph = RouteGraph()
        source = path.read_text(encoding="utf-8", errors="replace")
        rel = self._rel(path)

        module_id = self._node_id(path, rel, 0)
        graph.add_node(RouteNode(id=module_id, label=rel, kind=NodeKind.MODULE, file=rel))

        # Class definitions
        android_base = {"Activity", "Fragment", "ViewModel", "Service", "BroadcastReceiver"}
        for m in _CLASS_DEF.finditer(source):
            name = m.group(1)
            parent = m.group(2) or m.group(3) or m.group(4) or ""
            line = source[: m.start()].count("\n") + 1
            kind = NodeKind.UI_ELEMENT if any(b in parent for b in android_base) else NodeKind.FUNCTION
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
        for m in _JAVA_METHOD.finditer(source):
            name = m.group(1)
            raw_params = m.group(2)
            params = []
            for p in raw_params.split(","):
                p = p.strip()
                if p:
                    parts = p.split()
                    params.append(parts[-1] if len(parts) >= 2 else p)
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

        # onClick listeners
        for i, m in enumerate(_ONCLICK.finditer(source)):
            line = source[: m.start()].count("\n") + 1
            evt_id = self._node_id(path, f"onClick[{i}]", line)
            graph.add_node(
                RouteNode(
                    id=evt_id,
                    label="onClick",
                    kind=NodeKind.EVENT,
                    file=rel,
                    line=line,
                )
            )
            graph.add_edge(RouteEdge(module_id, evt_id, "handles"))

        # Intent navigation
        for m in _INTENT.finditer(source):
            target = m.group(1)
            line = source[: m.start()].count("\n") + 1
            ep_id = f"endpoint:ACTIVITY:{target}"
            graph.add_node(
                RouteNode(
                    id=ep_id,
                    label=f"startActivity {target}",
                    kind=NodeKind.ENDPOINT,
                    file=rel,
                    line=line,
                )
            )
            graph.add_edge(RouteEdge(module_id, ep_id, "navigates"))

        # Retrofit HTTP calls
        for m in _RETROFIT.finditer(source):
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
                    metadata={"method": method, "framework": "retrofit"},
                )
            )
            graph.add_edge(RouteEdge(module_id, ep_id, "calls"))

        # OkHttp
        for m in _OKHTTP.finditer(source):
            url = m.group(1)
            line = source[: m.start()].count("\n") + 1
            ep_id = f"endpoint:HTTP:{url}"
            graph.add_node(
                RouteNode(id=ep_id, label=url, kind=NodeKind.ENDPOINT, file=rel, line=line)
            )
            graph.add_edge(RouteEdge(module_id, ep_id, "calls"))

        # Room @Query
        for m in _ROOM_QUERY.finditer(source):
            snippet = m.group(1).strip()[:80]
            line = source[: m.start()].count("\n") + 1
            sql_id = self._node_id(path, f"SQL:{snippet[:20]}", line)
            graph.add_node(
                RouteNode(
                    id=sql_id,
                    label=snippet,
                    kind=NodeKind.SQL,
                    file=rel,
                    line=line,
                    metadata={"framework": "room"},
                )
            )
            graph.add_edge(RouteEdge(module_id, sql_id, "executes"))

        # SQLiteDatabase
        for m in _SQLITE_EXEC.finditer(source):
            snippet = m.group(1).strip()[:80]
            line = source[: m.start()].count("\n") + 1
            sql_id = self._node_id(path, f"SQL:{snippet[:20]}", line)
            graph.add_node(
                RouteNode(id=sql_id, label=snippet, kind=NodeKind.SQL, file=rel, line=line)
            )
            graph.add_edge(RouteEdge(module_id, sql_id, "executes"))

        return graph
