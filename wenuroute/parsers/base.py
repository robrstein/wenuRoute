"""Base parser interface that all language parsers must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from wenuroute.models import RouteGraph


class BaseParser(ABC):
    """Abstract base class for language-specific parsers."""

    #: File extensions this parser handles (lower-case, with leading dot).
    EXTENSIONS: tuple[str, ...] = ()

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def can_parse(self, path: Path) -> bool:
        """Return True if this parser can handle the given file."""
        return path.suffix.lower() in self.EXTENSIONS

    @abstractmethod
    def parse(self, path: Path) -> RouteGraph:
        """Parse *path* and return a partial RouteGraph."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rel(self, path: Path) -> str:
        """Return path relative to project root (as a POSIX string)."""
        try:
            return path.relative_to(self.project_root).as_posix()
        except ValueError:
            return path.as_posix()

    def _node_id(self, path: Path, name: str, line: int = 0) -> str:
        return f"{self._rel(path)}:{line}:{name}"
