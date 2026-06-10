"""Node.js / Express parser.

Detects:
- require() / import statements
- Express route definitions (app.get, router.post, …)
- Function definitions
- Database queries (knex, mongoose, sequelize patterns)
"""

from __future__ import annotations

import re
from pathlib import Path

from wenuroute.models import NodeKind, RouteEdge, RouteGraph, RouteNode
from wenuroute.parsers.base import BaseParser

_REQUIRE = re.compile(
    r"""(?:require\s*\(\s*['"]([^'"]+)['"]\s*\)|import\s+.*?\s+from\s+['"]([^'"]+)['"])""",
    re.MULTILINE,
)

_EXPRESS_ROUTE = re.compile(
    r"""(?:app|router)\s*\.\s*(get|post|put|delete|patch|all)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE | re.MULTILINE,
)

_FUNCTION_DEF = re.compile(
    r"""(?:function\s+(\w+)\s*\(([^)]*)\)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>)""",
    re.MULTILINE,
)

_DB_CALL = re.compile(
    r"""(?:\.find\(|\.findOne\(|\.query\(|\.select\(|\.insert\(|\.update\(|\.delete\(|knex\s*\()""",
    re.MULTILINE,
)

_SQL_TEMPLATE = re.compile(
    r"""(?:query|execute|db\.run|db\.all|db\.get)\s*\(\s*['"`](.*?)['"`]""",
    re.IGNORECASE | re.DOTALL,
)


class NodejsParser(BaseParser):
    """Parse Node.js / Express JavaScript files."""

    EXTENSIONS = (".js", ".mjs", ".cjs", ".ts")

    def parse(self, path: Path) -> RouteGraph:
        graph = RouteGraph()
        source = path.read_text(encoding="utf-8", errors="replace")
        rel = self._rel(path)

        module_id = self._node_id(path, rel, 0)
        graph.add_node(RouteNode(id=module_id, label=rel, kind=NodeKind.MODULE, file=rel))

        # require / import
        for m in _REQUIRE.finditer(source):
            imported = m.group(1) or m.group(2)
            imp_id = f"import:{imported}"
            graph.add_node(
                RouteNode(id=imp_id, label=imported, kind=NodeKind.MODULE, file=imported)
            )
            graph.add_edge(RouteEdge(module_id, imp_id, "imports"))

        # Express routes
        for m in _EXPRESS_ROUTE.finditer(source):
            method = m.group(1).upper()
            route = m.group(2)
            line = source[: m.start()].count("\n") + 1
            ep_id = f"endpoint:{method}:{route}"
            graph.add_node(
                RouteNode(
                    id=ep_id,
                    label=f"{method} {route}",
                    kind=NodeKind.ENDPOINT,
                    file=rel,
                    line=line,
                    metadata={"method": method, "framework": "express"},
                )
            )
            graph.add_edge(RouteEdge(module_id, ep_id, "defines"))

        # Function definitions
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

        # DB / ORM calls
        for m in _DB_CALL.finditer(source):
            line = source[: m.start()].count("\n") + 1
            call_name = m.group(0).strip("(. ")
            db_id = self._node_id(path, f"db:{call_name}", line)
            graph.add_node(
                RouteNode(
                    id=db_id,
                    label=call_name,
                    kind=NodeKind.SQL,
                    file=rel,
                    line=line,
                )
            )
            graph.add_edge(RouteEdge(module_id, db_id, "executes"))

        # Raw SQL
        for m in _SQL_TEMPLATE.finditer(source):
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
                )
            )
            graph.add_edge(RouteEdge(module_id, sql_id, "executes"))

        return graph
