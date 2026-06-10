"""Data models shared across all parsers and the analyser."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeKind(str, Enum):
    """High-level category of a graph node."""

    UI_ELEMENT = "ui_element"       # button, link, form field, widget …
    FUNCTION = "function"           # JS/Python/Dart/Java function or method
    ENDPOINT = "endpoint"           # HTTP route (REST, GraphQL …)
    SQL = "sql"                     # SQL query or ORM call
    STYLE = "style"                 # CSS class / stylesheet reference
    EVENT = "event"                 # DOM event, gesture, intent …
    MODULE = "module"               # file / module node (top-level grouping)
    UNKNOWN = "unknown"


@dataclass
class RouteNode:
    """A single node in the execution-route graph."""

    id: str                         # unique identifier (file:line:name)
    label: str                      # human-readable short label
    kind: NodeKind = NodeKind.UNKNOWN
    file: str = ""                  # source file path (relative to project root)
    line: int = 0                   # line number (1-based)
    params: list[str] = field(default_factory=list)   # parameter names only
    metadata: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RouteNode) and self.id == other.id


@dataclass
class RouteEdge:
    """A directed edge from one node to another."""

    source_id: str
    target_id: str
    label: str = ""                 # e.g. "calls", "triggers", "renders"

    def __hash__(self) -> int:
        return hash((self.source_id, self.target_id, self.label))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, RouteEdge)
            and self.source_id == other.source_id
            and self.target_id == other.target_id
            and self.label == other.label
        )


@dataclass
class RouteGraph:
    """The full execution-route graph for a project."""

    nodes: dict[str, RouteNode] = field(default_factory=dict)
    edges: list[RouteEdge] = field(default_factory=list)

    def add_node(self, node: RouteNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: RouteEdge) -> None:
        if edge not in self.edges:
            self.edges.append(edge)

    def merge(self, other: "RouteGraph") -> None:
        """Merge another graph into this one in-place."""
        self.nodes.update(other.nodes)
        for edge in other.edges:
            self.add_edge(edge)
