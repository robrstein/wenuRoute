"""Project analyzer — orchestrates parsers over a directory tree."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from wenuroute.models import RouteGraph
from wenuroute.parsers import ALL_PARSERS, BaseParser


class Analyzer:
    """Walk a project directory, dispatch files to the appropriate parser,
    and merge all partial graphs into a single RouteGraph.
    """

    # Directories to skip unconditionally
    _SKIP_DIRS = {
        ".git", ".hg", ".svn",
        "node_modules", "__pycache__", ".venv", "venv", "env",
        "build", "dist", ".gradle", ".idea", ".vscode",
        "ios", "android/.gradle",
    }

    def __init__(
        self,
        project_root: Path,
        *,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self._progress = progress_callback or (lambda _: None)

        # Instantiate all parsers once
        self._parsers: list[BaseParser] = [
            P(self.project_root) for P in ALL_PARSERS
        ]

        # Build extension → parser index for fast lookup
        self._ext_map: dict[str, list[BaseParser]] = {}
        for parser in self._parsers:
            for ext in parser.EXTENSIONS:
                self._ext_map.setdefault(ext, []).append(parser)

    # ------------------------------------------------------------------

    def analyze(self) -> RouteGraph:
        """Analyze the entire project and return a merged RouteGraph."""
        graph = RouteGraph()
        files = self._collect_files()
        for file_path in files:
            parsers = self._parsers_for(file_path)
            for parser in parsers:
                try:
                    partial = parser.parse(file_path)
                    graph.merge(partial)
                    self._progress(f"  parsed  {parser.__class__.__name__}: {file_path.name}")
                except Exception as exc:  # noqa: BLE001
                    self._progress(f"  [warn]  {file_path.name}: {exc}")
        return graph

    # ------------------------------------------------------------------

    def _collect_files(self) -> list[Path]:
        files: list[Path] = []
        for path in self.project_root.rglob("*"):
            if not path.is_file():
                continue
            # Skip blacklisted directories
            if any(skip in path.parts for skip in self._SKIP_DIRS):
                continue
            # Only include files whose extension is known to any parser
            if self._parsers_for(path):
                files.append(path)
        return files

    def _parsers_for(self, path: Path) -> list[BaseParser]:
        ext = path.suffix.lower()
        return self._ext_map.get(ext, [])
