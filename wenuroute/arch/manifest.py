"""Dependency-manifest scanner.

Best-effort, tolerant scan of the project's declared external dependencies:

- ``requirements.txt``  (pip)
- ``pyproject.toml``    ``[project.dependencies]`` / ``[project.optional-dependencies]``  (pip)
- ``package.json``      ``dependencies`` / ``devDependencies``  (npm)

Manifests are searched for *anywhere* under the project root (skipping the
same noise directories the main :class:`~wenuroute.analyzer.Analyzer` skips)
so a monorepo's ``backend/requirements.txt`` and each frontend package's
``package.json`` are all picked up, not just ones at the project root.

Each sub-scanner returns a :class:`~wenuroute.models.RouteGraph` and never raises —
a missing or malformed manifest simply contributes nothing, mirroring the
tolerant, regex-first style of the language parsers in ``wenuroute/parsers/``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wenuroute.models import NodeKind, RouteEdge, RouteGraph, RouteNode

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - exercised on <3.11 only
    import tomli as tomllib  # type: ignore[no-redef]

_REQ_LINE = re.compile(
    r"""^\s*([A-Za-z0-9_.\-]+)\s*(?P<spec>[=<>!~]{1,2}=?\s*[\w.\*]+)?""",
)

# Strip any PEP 508 marker/extra suffix (e.g. "requests[socks]>=2; python_version>='3.8'")
_PEP508_NAME = re.compile(r"""^\s*([A-Za-z0-9_.\-]+)""")


# Directories skipped while walking the tree for manifests — mirrors
# wenuroute.analyzer.Analyzer._SKIP_DIRS so backend/frontend vendoring
# doesn't get scanned as if it were the project's own dependency list.
_SKIP_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".venv", "venv", "env",
    "build", "dist", ".gradle", ".idea", ".vscode",
    "ios", "android/.gradle",
}


def _find_manifests(project_root: Path, filename: str) -> list[Path]:
    found = []
    for path in project_root.rglob(filename):
        if path.is_file() and not any(part in _SKIP_DIRS for part in path.relative_to(project_root).parts):
            found.append(path)
    return sorted(found)


def _manifest_node(rel_path: str) -> RouteNode:
    return RouteNode(
        id=f"manifest:{rel_path}",
        label=rel_path,
        kind=NodeKind.MODULE,
        file=rel_path,
    )


def _dependency_node(ecosystem: str, name: str, **metadata: object) -> RouteNode:
    return RouteNode(
        id=f"dependency:{ecosystem}:{name}",
        label=name,
        kind=NodeKind.DEPENDENCY,
        metadata=dict(metadata),
    )


def _scan_requirements_txt(path: Path, rel: str) -> RouteGraph:
    graph = RouteGraph()

    manifest_id = f"manifest:{rel}"
    graph.add_node(_manifest_node(rel))

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = _REQ_LINE.match(line)
        if not m:
            continue
        name = m.group(1)
        if not name:
            continue
        version = (m.group("spec") or "").strip() or None
        dep = _dependency_node("pip", name, manifest=rel, version=version)
        graph.add_node(dep)
        graph.add_edge(RouteEdge(manifest_id, dep.id, "depends_on"))

    return graph


_PEP508_SPEC = re.compile(
    r"""^\s*[A-Za-z0-9_.\-]+\s*(?:\[[^\]]*\])?\s*(?P<spec>[=<>!~]{1,2}=?[^;]+)?"""
)


def _dep_name_from_pep508(spec: str) -> str | None:
    m = _PEP508_NAME.match(spec)
    return m.group(1) if m else None


def _dep_version_from_pep508(spec: str) -> str | None:
    m = _PEP508_SPEC.match(spec)
    version = m.group("spec") if m else None
    return version.strip() or None if version else None


def _scan_pyproject_toml(path: Path, rel: str) -> RouteGraph:
    graph = RouteGraph()

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return graph

    project = data.get("project")
    if not isinstance(project, dict):
        return graph

    manifest_id = f"manifest:{rel}"
    graph.add_node(_manifest_node(rel))

    for spec in project.get("dependencies", []) or []:
        name = _dep_name_from_pep508(str(spec))
        if not name:
            continue
        dep = _dependency_node(
            "pip", name, manifest=rel, version=_dep_version_from_pep508(str(spec))
        )
        graph.add_node(dep)
        graph.add_edge(RouteEdge(manifest_id, dep.id, "depends_on"))

    optional = project.get("optional-dependencies", {}) or {}
    if isinstance(optional, dict):
        for group, specs in optional.items():
            for spec in specs or []:
                name = _dep_name_from_pep508(str(spec))
                if not name:
                    continue
                dep = _dependency_node(
                    "pip", name, manifest=rel, optional_group=group,
                    version=_dep_version_from_pep508(str(spec)),
                )
                graph.add_node(dep)
                graph.add_edge(RouteEdge(manifest_id, dep.id, "depends_on"))

    return graph


def _scan_package_json(path: Path, rel: str) -> RouteGraph:
    graph = RouteGraph()

    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return graph
    if not isinstance(data, dict):
        return graph

    manifest_id = f"manifest:{rel}"
    graph.add_node(_manifest_node(rel))

    for key, is_dev in (("dependencies", False), ("devDependencies", True)):
        deps = data.get(key)
        if not isinstance(deps, dict):
            continue
        for name, version in deps.items():
            dep = _dependency_node(
                "npm", name, manifest=rel, version=version, dev=is_dev
            )
            graph.add_node(dep)
            graph.add_edge(RouteEdge(manifest_id, dep.id, "depends_on"))

    return graph


def scan_dependencies(project_root: Path) -> RouteGraph:
    """Best-effort scan of dependency manifests anywhere under *project_root*.

    Never raises: any individual scanner failure is swallowed so one
    malformed manifest doesn't abort the whole ``--arch`` run.
    """
    graph = RouteGraph()
    scanners = (
        ("requirements.txt", _scan_requirements_txt),
        ("pyproject.toml", _scan_pyproject_toml),
        ("package.json", _scan_package_json),
    )
    for filename, scan in scanners:
        for path in _find_manifests(project_root, filename):
            rel = path.relative_to(project_root).as_posix()
            try:
                graph.merge(scan(path, rel))
            except Exception:
                pass
    return graph
