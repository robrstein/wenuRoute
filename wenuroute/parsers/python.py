"""Python backend parser.

Detects:
- Function and class definitions
- Flask / FastAPI / Django URL routes (decorators and urlpatterns)
- SQL queries (raw strings and ORM calls)
- Function calls between detected symbols
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Union

from wenuroute.models import NodeKind, RouteEdge, RouteGraph, RouteNode
from wenuroute.parsers.base import BaseParser

_SQL_PATTERN = re.compile(
    r"""(?:execute|query|raw|cursor\.execute)\s*\(\s*['"`]{1,3}(.*?)['"`]{1,3}""",
    re.IGNORECASE | re.DOTALL,
)

_FLASK_ROUTE = re.compile(
    r"""@\w+\.route\s*\(\s*['"]([^'"]+)['"](?:[^)]*methods\s*=\s*\[([^\]]+)\])?""",
    re.MULTILINE,
)

_FASTAPI_ROUTE = re.compile(
    r"""@\w+\.(get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE | re.MULTILINE,
)

_DJANGO_URL = re.compile(
    r"""(?:path|re_path|url)\s*\(\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)


class PythonParser(BaseParser):
    """Parse Python source files."""

    EXTENSIONS = (".py",)

    def parse(self, path: Path) -> RouteGraph:
        graph = RouteGraph()
        source = path.read_text(encoding="utf-8", errors="replace")
        rel = self._rel(path)

        # Module node
        module_id = self._node_id(path, rel, 0)
        graph.add_node(RouteNode(id=module_id, label=rel, kind=NodeKind.MODULE, file=rel))

        # AST-based analysis
        try:
            tree = ast.parse(source, filename=str(path))
            self._walk_ast(graph, tree, path, rel, module_id)
        except SyntaxError:
            pass  # fall back to regex only

        # Flask routes
        for m in _FLASK_ROUTE.finditer(source):
            route = m.group(1)
            methods_raw = m.group(2) or "GET"
            methods = [x.strip().strip("'\"") for x in methods_raw.split(",")]
            line = source[: m.start()].count("\n") + 1
            for method in methods:
                ep_id = f"endpoint:{method.upper()}:{route}"
                graph.add_node(
                    RouteNode(
                        id=ep_id,
                        label=f"{method.upper()} {route}",
                        kind=NodeKind.ENDPOINT,
                        file=rel,
                        line=line,
                        metadata={"method": method.upper(), "framework": "flask"},
                    )
                )
                graph.add_edge(RouteEdge(module_id, ep_id, "defines"))

        # FastAPI routes
        for m in _FASTAPI_ROUTE.finditer(source):
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
                    metadata={"method": method, "framework": "fastapi"},
                )
            )
            graph.add_edge(RouteEdge(module_id, ep_id, "defines"))

        # Django urlpatterns
        for m in _DJANGO_URL.finditer(source):
            route = m.group(1)
            line = source[: m.start()].count("\n") + 1
            ep_id = f"endpoint:URL:{route}"
            graph.add_node(
                RouteNode(
                    id=ep_id,
                    label=f"url {route}",
                    kind=NodeKind.ENDPOINT,
                    file=rel,
                    line=line,
                    metadata={"framework": "django"},
                )
            )
            graph.add_edge(RouteEdge(module_id, ep_id, "defines"))

        # SQL queries (raw strings)
        for m in _SQL_PATTERN.finditer(source):
            query_snippet = m.group(1).strip()[:80]
            line = source[: m.start()].count("\n") + 1
            sql_id = self._node_id(path, f"SQL:{query_snippet[:20]}", line)
            graph.add_node(
                RouteNode(
                    id=sql_id,
                    label=query_snippet,
                    kind=NodeKind.SQL,
                    file=rel,
                    line=line,
                )
            )
            graph.add_edge(RouteEdge(module_id, sql_id, "executes"))

        return graph

    # ------------------------------------------------------------------

    def _walk_ast(
        self,
        graph: RouteGraph,
        tree: ast.AST,
        path: Path,
        rel: str,
        module_id: str,
    ) -> None:
        """Walk the AST and extract function / class definitions and calls."""

        AnyDef = Union[ast.FunctionDef, ast.AsyncFunctionDef]

        def _params(node: AnyDef) -> list[str]:
            args = node.args
            return [a.arg for a in args.args + args.posonlyargs + args.kwonlyargs]

        def _visit(node: ast.AST, parent_id: str) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_id = self._node_id(path, node.name, node.lineno)
                params = _params(node)  # type: ignore[arg-type]
                graph.add_node(
                    RouteNode(
                        id=fn_id,
                        label=node.name,
                        kind=NodeKind.FUNCTION,
                        file=rel,
                        line=node.lineno,
                        params=params,
                    )
                )
                graph.add_edge(RouteEdge(parent_id, fn_id, "defines"))

                # Check for ORM SQL patterns inside the function body
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        _handle_call(child, fn_id)

                for child in ast.iter_child_nodes(node):
                    _visit(child, fn_id)

            elif isinstance(node, ast.ClassDef):
                cls_id = self._node_id(path, node.name, node.lineno)
                graph.add_node(
                    RouteNode(
                        id=cls_id,
                        label=node.name,
                        kind=NodeKind.FUNCTION,
                        file=rel,
                        line=node.lineno,
                    )
                )
                graph.add_edge(RouteEdge(parent_id, cls_id, "defines"))
                for child in ast.iter_child_nodes(node):
                    _visit(child, cls_id)
            else:
                for child in ast.iter_child_nodes(node):
                    _visit(child, parent_id)

        def _handle_call(node: ast.Call, parent_id: str) -> None:
            """Detect ORM / SQL calls."""
            func = node.func
            if isinstance(func, ast.Attribute):
                method = func.attr.lower()
                if method in {"filter", "filter_by", "query", "execute", "raw", "all", "get"}:
                    line = getattr(node, "lineno", 0)
                    sql_id = self._node_id(path, f"ORM:{method}", line)
                    graph.add_node(
                        RouteNode(
                            id=sql_id,
                            label=f"ORM.{method}()",
                            kind=NodeKind.SQL,
                            file=rel,
                            line=line,
                        )
                    )
                    graph.add_edge(RouteEdge(parent_id, sql_id, "executes"))

        _visit(tree, module_id)
