"""Dependency-manifest scanner.

Best-effort, tolerant scan of the project's declared external dependencies:

- ``requirements.txt``  (pip)
- ``pyproject.toml``    ``[project.dependencies]`` / ``[project.optional-dependencies]``  (pip)
- ``package.json``      ``dependencies`` / ``devDependencies``  (npm)

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


def _manifest_node(manifest_file: str) -> RouteNode:
    return RouteNode(
        id=f"manifest:{manifest_file}",
        label=manifest_file,
        kind=NodeKind.MODULE,
        file=manifest_file,
    )


def _dependency_node(ecosystem: str, name: str, **metadata: object) -> RouteNode:
    return RouteNode(
        id=f"dependency:{ecosystem}:{name}",
        label=name,
        kind=NodeKind.DEPENDENCY,
        metadata=dict(metadata),
    )


def _scan_requirements_txt(project_root: Path) -> RouteGraph:
    graph = RouteGraph()
    path = project_root / "requirements.txt"
    if not path.is_file():
        return graph

    manifest_id = "manifest:requirements.txt"
    graph.add_node(_manifest_node("requirements.txt"))

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
        dep = _dependency_node("pip", name, manifest="requirements.txt", version=version)
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


def _scan_pyproject_toml(project_root: Path) -> RouteGraph:
    graph = RouteGraph()
    path = project_root / "pyproject.toml"
    if not path.is_file():
        return graph

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return graph

    project = data.get("project")
    if not isinstance(project, dict):
        return graph

    manifest_id = "manifest:pyproject.toml"
    graph.add_node(_manifest_node("pyproject.toml"))

    for spec in project.get("dependencies", []) or []:
        name = _dep_name_from_pep508(str(spec))
        if not name:
            continue
        dep = _dependency_node(
            "pip", name, manifest="pyproject.toml", version=_dep_version_from_pep508(str(spec))
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
                    "pip", name, manifest="pyproject.toml", optional_group=group,
                    version=_dep_version_from_pep508(str(spec)),
                )
                graph.add_node(dep)
                graph.add_edge(RouteEdge(manifest_id, dep.id, "depends_on"))

    return graph


def _scan_package_json(project_root: Path) -> RouteGraph:
    graph = RouteGraph()
    path = project_root / "package.json"
    if not path.is_file():
        return graph

    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return graph
    if not isinstance(data, dict):
        return graph

    manifest_id = "manifest:package.json"
    graph.add_node(_manifest_node("package.json"))

    for key, is_dev in (("dependencies", False), ("devDependencies", True)):
        deps = data.get(key)
        if not isinstance(deps, dict):
            continue
        for name, version in deps.items():
            dep = _dependency_node(
                "npm", name, manifest="package.json", version=version, dev=is_dev
            )
            graph.add_node(dep)
            graph.add_edge(RouteEdge(manifest_id, dep.id, "depends_on"))

    return graph


def scan_dependencies(project_root: Path) -> RouteGraph:
    """Best-effort scan of dependency manifests under *project_root*.

    Never raises: any individual scanner failure is swallowed so one
    malformed manifest doesn't abort the whole ``--arch`` run.
    """
    graph = RouteGraph()
    for scan in (_scan_requirements_txt, _scan_pyproject_toml, _scan_package_json):
        try:
            graph.merge(scan(project_root))
        except Exception:
            pass
    return graph
