"""HTML parser — detects buttons, links, forms, inline scripts and style refs."""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from wenuroute.models import NodeKind, RouteEdge, RouteGraph, RouteNode
from wenuroute.parsers.base import BaseParser

_JS_HANDLERS = re.compile(
    r"on\w+",        # onclick, onsubmit, onchange, …
    re.IGNORECASE,
)
_FUNC_CALL = re.compile(r"(\w[\w.]*)\s*\(([^)]*)\)")


class HtmlParser(BaseParser):
    """Parse HTML files for UI elements and their event handlers."""

    EXTENSIONS = (".html", ".htm")

    def parse(self, path: Path) -> RouteGraph:
        graph = RouteGraph()
        source = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(source, "lxml")
        rel = self._rel(path)

        # Module node (the file itself)
        module_id = self._node_id(path, rel, 0)
        graph.add_node(RouteNode(id=module_id, label=rel, kind=NodeKind.MODULE, file=rel))

        # Collect <link rel="stylesheet"> references
        for tag in soup.find_all("link", rel="stylesheet"):
            href = tag.get("href", "")
            if href:
                css_id = f"css:{href}"
                graph.add_node(
                    RouteNode(id=css_id, label=href, kind=NodeKind.STYLE, file=href)
                )
                graph.add_edge(RouteEdge(module_id, css_id, "uses"))

        # Collect <style> blocks
        for i, style_tag in enumerate(soup.find_all("style")):
            style_id = self._node_id(path, f"<style[{i}]>", 0)
            graph.add_node(
                RouteNode(id=style_id, label=f"<style[{i}]>", kind=NodeKind.STYLE, file=rel)
            )
            graph.add_edge(RouteEdge(module_id, style_id, "uses"))

        # Interactive elements: buttons, links, inputs, forms
        interactive_tags = ("button", "a", "input", "form", "select", "textarea")
        for tag in soup.find_all(interactive_tags):
            if not isinstance(tag, Tag):
                continue
            self._process_element(graph, path, rel, module_id, tag)

        # <script src="..."> references
        for script_tag in soup.find_all("script", src=True):
            src = script_tag.get("src", "")
            js_id = f"js:{src}"
            graph.add_node(
                RouteNode(id=js_id, label=src, kind=NodeKind.FUNCTION, file=src)
            )
            graph.add_edge(RouteEdge(module_id, js_id, "imports"))

        # Inline <script> blocks — extract function calls
        for i, script_tag in enumerate(soup.find_all("script", src=False)):
            script_content = script_tag.get_text()
            for match in _FUNC_CALL.finditer(script_content):
                fn_name = match.group(1)
                raw_params = match.group(2)
                params = [p.strip() for p in raw_params.split(",") if p.strip()]
                fn_id = f"{rel}:inline-script[{i}]:{fn_name}"
                graph.add_node(
                    RouteNode(
                        id=fn_id,
                        label=fn_name,
                        kind=NodeKind.FUNCTION,
                        file=rel,
                        params=params,
                    )
                )
                graph.add_edge(RouteEdge(module_id, fn_id, "calls"))

        return graph

    # ------------------------------------------------------------------

    def _process_element(
        self,
        graph: RouteGraph,
        path: Path,
        rel: str,
        module_id: str,
        tag: Tag,
    ) -> None:
        tag_name = tag.name or "element"
        text = tag.get_text(strip=True)[:40] or tag.get("id") or tag.get("name") or tag_name
        label = f"<{tag_name}> {text}"
        elem_id = self._node_id(path, label, 0)

        graph.add_node(
            RouteNode(id=elem_id, label=label, kind=NodeKind.UI_ELEMENT, file=rel)
        )
        graph.add_edge(RouteEdge(module_id, elem_id, "contains"))

        # Event-handler attributes
        for attr, value in tag.attrs.items():
            if _JS_HANDLERS.fullmatch(attr) and value:
                event_id = f"{elem_id}:{attr}"
                graph.add_node(
                    RouteNode(
                        id=event_id,
                        label=f"{attr}: {value[:60]}",
                        kind=NodeKind.EVENT,
                        file=rel,
                    )
                )
                graph.add_edge(RouteEdge(elem_id, event_id, "triggers"))

                # Detect function calls inside the handler
                for match in _FUNC_CALL.finditer(str(value)):
                    fn_name = match.group(1)
                    raw_params = match.group(2)
                    params = [p.strip() for p in raw_params.split(",") if p.strip()]
                    fn_id = f"{rel}:handler:{fn_name}"
                    graph.add_node(
                        RouteNode(
                            id=fn_id,
                            label=fn_name,
                            kind=NodeKind.FUNCTION,
                            file=rel,
                            params=params,
                        )
                    )
                    graph.add_edge(RouteEdge(event_id, fn_id, "calls"))

        # <a href="..."> → possible endpoint
        if tag_name == "a":
            href = tag.get("href", "")
            if href and not href.startswith("#"):
                ep_id = f"endpoint:{href}"
                graph.add_node(
                    RouteNode(id=ep_id, label=href, kind=NodeKind.ENDPOINT, file=rel)
                )
                graph.add_edge(RouteEdge(elem_id, ep_id, "navigates"))

        # <form action="...">
        if tag_name == "form":
            action = tag.get("action", "")
            method = tag.get("method", "GET").upper()
            if action:
                ep_id = f"endpoint:{method}:{action}"
                graph.add_node(
                    RouteNode(
                        id=ep_id,
                        label=f"{method} {action}",
                        kind=NodeKind.ENDPOINT,
                        file=rel,
                        metadata={"method": method},
                    )
                )
                graph.add_edge(RouteEdge(elem_id, ep_id, "submits"))
