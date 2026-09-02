"""Tests for the wenuroute.arch package (architecture digital-library mode)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from wenuroute.models import NodeKind, RouteEdge, RouteGraph, RouteNode


# ---------------------------------------------------------------------------
# Manifest scanner
# ---------------------------------------------------------------------------

class TestManifestScanner:
    def test_requirements_txt_basic(self, tmp_path: Path):
        from wenuroute.arch.manifest import scan_dependencies

        (tmp_path / "requirements.txt").write_text(
            textwrap.dedent("""\
            flask==2.0
            # a comment
            requests>=2
            -e .
            """)
        )
        graph = scan_dependencies(tmp_path)
        dep_labels = {n.label for n in graph.nodes.values() if n.kind == NodeKind.DEPENDENCY}
        assert "flask" in dep_labels
        assert "requests" in dep_labels

    def test_requirements_txt_missing_file_no_crash(self, tmp_path: Path):
        from wenuroute.arch.manifest import scan_dependencies

        graph = scan_dependencies(tmp_path)
        assert isinstance(graph, RouteGraph)
        assert not graph.nodes

    def test_pyproject_toml_project_dependencies(self, tmp_path: Path):
        from wenuroute.arch.manifest import scan_dependencies

        (tmp_path / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "demo"
            dependencies = ["click>=8.1", "rich"]
            """)
        )
        graph = scan_dependencies(tmp_path)
        dep_labels = {n.label for n in graph.nodes.values() if n.kind == NodeKind.DEPENDENCY}
        assert "click" in dep_labels
        assert "rich" in dep_labels

    def test_pyproject_toml_optional_dependencies_group_tagged(self, tmp_path: Path):
        from wenuroute.arch.manifest import scan_dependencies

        (tmp_path / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            name = "demo"
            dependencies = []

            [project.optional-dependencies]
            dev = ["pytest>=7.0"]
            """)
        )
        graph = scan_dependencies(tmp_path)
        pytest_nodes = [n for n in graph.nodes.values() if n.label == "pytest"]
        assert pytest_nodes
        assert pytest_nodes[0].metadata.get("optional_group") == "dev"

    def test_pyproject_toml_malformed_does_not_crash(self, tmp_path: Path):
        from wenuroute.arch.manifest import scan_dependencies

        (tmp_path / "pyproject.toml").write_text("this is not [ valid toml")
        graph = scan_dependencies(tmp_path)
        assert isinstance(graph, RouteGraph)

    def test_package_json_dependencies_and_dev(self, tmp_path: Path):
        from wenuroute.arch.manifest import scan_dependencies

        (tmp_path / "package.json").write_text(
            '{"dependencies": {"express": "^4.18.0"}, '
            '"devDependencies": {"jest": "^29.0.0"}}'
        )
        graph = scan_dependencies(tmp_path)
        by_label = {n.label: n for n in graph.nodes.values() if n.kind == NodeKind.DEPENDENCY}
        assert "express" in by_label
        assert "jest" in by_label
        assert by_label["jest"].metadata.get("dev") is True
        assert not by_label["express"].metadata.get("dev")

    def test_package_json_malformed_json_no_crash(self, tmp_path: Path):
        from wenuroute.arch.manifest import scan_dependencies

        (tmp_path / "package.json").write_text("{not valid json")
        graph = scan_dependencies(tmp_path)
        assert isinstance(graph, RouteGraph)

    def test_scan_dependencies_merges_all_three(self, tmp_path: Path):
        from wenuroute.arch.manifest import scan_dependencies

        (tmp_path / "requirements.txt").write_text("flask==2.0\n")
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "demo"\ndependencies = ["click"]\n'
        )
        (tmp_path / "package.json").write_text('{"dependencies": {"express": "^4.0.0"}}')

        graph = scan_dependencies(tmp_path)
        dep_labels = {n.label for n in graph.nodes.values() if n.kind == NodeKind.DEPENDENCY}
        assert {"flask", "click", "express"} <= dep_labels


# ---------------------------------------------------------------------------
# Sequence-chain derivation
# ---------------------------------------------------------------------------

class TestSequenceChains:
    def test_simple_chain_endpoint_to_function_to_sql(self):
        from wenuroute.arch.sequence import derive_sequences

        graph = RouteGraph()
        graph.add_node(RouteNode(id="ep", label="POST /login", kind=NodeKind.ENDPOINT, file="app.py", line=1))
        graph.add_node(RouteNode(id="fn", label="validate_user", kind=NodeKind.FUNCTION, file="app.py", line=5))
        graph.add_node(RouteNode(id="sql", label="SELECT * FROM users", kind=NodeKind.SQL, file="app.py", line=10))
        graph.add_edge(RouteEdge("ep", "fn", "calls"))
        graph.add_edge(RouteEdge("fn", "sql", "executes"))

        sequences = derive_sequences(graph)
        assert len(sequences) == 1
        steps = sequences[0]["steps"]
        assert [s["label"] for s in steps] == ["POST /login", "validate_user", "SELECT * FROM users"]
        assert "edge_label" not in steps[0]
        assert steps[1]["edge_label"] == "calls"
        assert steps[2]["edge_label"] == "executes"

    def test_no_entry_points_yields_no_sequences(self):
        from wenuroute.arch.sequence import derive_sequences

        graph = RouteGraph()
        graph.add_node(RouteNode(id="mod", label="app.py", kind=NodeKind.MODULE, file="app.py"))
        graph.add_node(RouteNode(id="style", label="main.css", kind=NodeKind.STYLE, file="main.css"))
        graph.add_edge(RouteEdge("mod", "style", "uses"))

        assert derive_sequences(graph) == []

    def test_cycle_does_not_infinite_loop(self):
        from wenuroute.arch.sequence import derive_sequences

        graph = RouteGraph()
        graph.add_node(RouteNode(id="a", label="A", kind=NodeKind.ENDPOINT, file="a.py", line=1))
        graph.add_node(RouteNode(id="b", label="B", kind=NodeKind.FUNCTION, file="a.py", line=2))
        graph.add_edge(RouteEdge("a", "b", "calls"))
        graph.add_edge(RouteEdge("b", "a", "calls"))

        sequences = derive_sequences(graph)
        assert sequences  # terminates and returns something
        for seq in sequences:
            assert len(seq["steps"]) <= 8  # bounded, not runaway

    def test_max_chains_cap_respected(self):
        from wenuroute.arch.sequence import MAX_CHAINS, derive_sequences

        graph = RouteGraph()
        for i in range(MAX_CHAINS + 20):
            ep_id, fn_id = f"ep{i}", f"fn{i}"
            graph.add_node(RouteNode(id=ep_id, label=f"EP{i}", kind=NodeKind.ENDPOINT, file="a.py", line=i))
            graph.add_node(RouteNode(id=fn_id, label=f"FN{i}", kind=NodeKind.FUNCTION, file="a.py", line=i))
            graph.add_edge(RouteEdge(ep_id, fn_id, "calls"))

        sequences = derive_sequences(graph)
        assert len(sequences) <= MAX_CHAINS

    def test_max_depth_cap_respected(self):
        from wenuroute.arch.sequence import MAX_DEPTH, derive_sequences

        graph = RouteGraph()
        node_count = MAX_DEPTH + 10
        ids = [f"n{i}" for i in range(node_count)]
        graph.add_node(RouteNode(id=ids[0], label="Entry", kind=NodeKind.ENDPOINT, file="a.py", line=0))
        for i in range(1, node_count):
            graph.add_node(RouteNode(id=ids[i], label=f"F{i}", kind=NodeKind.FUNCTION, file="a.py", line=i))
            graph.add_edge(RouteEdge(ids[i - 1], ids[i], "calls"))

        sequences = derive_sequences(graph)
        assert sequences
        assert max(len(seq["steps"]) for seq in sequences) <= MAX_DEPTH + 1

    def test_non_flow_edges_excluded(self):
        from wenuroute.arch.sequence import derive_sequences

        graph = RouteGraph()
        graph.add_node(RouteNode(id="ep", label="GET /x", kind=NodeKind.ENDPOINT, file="a.py", line=1))
        graph.add_node(RouteNode(id="mod", label="a.py", kind=NodeKind.MODULE, file="a.py"))
        graph.add_edge(RouteEdge("ep", "mod", "imports"))

        assert derive_sequences(graph) == []


# ---------------------------------------------------------------------------
# render_arch_html smoke tests
# ---------------------------------------------------------------------------

class TestArchRenderSmoke:
    def _sample_graph(self) -> RouteGraph:
        graph = RouteGraph()
        graph.add_node(RouteNode(id="mod", label="app.py", kind=NodeKind.MODULE, file="app.py"))
        graph.add_node(RouteNode(id="ep", label="GET /health", kind=NodeKind.ENDPOINT, file="app.py", line=3))
        graph.add_node(RouteNode(id="fn", label="health", kind=NodeKind.FUNCTION, file="app.py", line=4))
        graph.add_edge(RouteEdge("mod", "ep", "defines"))
        graph.add_edge(RouteEdge("ep", "fn", "calls"))
        return graph

    def test_render_arch_html_runs_and_produces_html(self, tmp_path: Path):
        from wenuroute.arch.render import render_arch_html

        out = tmp_path / "wenuroute_arch.html"
        render_arch_html(self._sample_graph(), RouteGraph(), out)

        assert out.exists()
        text = out.read_text(encoding="utf-8")
        assert "<html" in text
        for section_id in (
            "view-library", "view-architecture", "view-sequence",
            "view-dataflow", "view-lifecycle", "view-pipeline",
        ):
            assert f'id="{section_id}"' in text
        assert "__ARCH_DATA__" not in text
        assert "__SEQ_DATA__" not in text
        assert "__KIND_COLOURS__" not in text

    def test_render_arch_html_with_dependencies(self, tmp_path: Path):
        from wenuroute.arch.render import render_arch_html

        dep_graph = RouteGraph()
        dep_graph.add_node(
            RouteNode(
                id="dependency:pip:flask",
                label="flask",
                kind=NodeKind.DEPENDENCY,
                metadata={"manifest": "requirements.txt", "version": "==2.0"},
            )
        )

        out = tmp_path / "wenuroute_arch.html"
        render_arch_html(self._sample_graph(), dep_graph, out)

        text = out.read_text(encoding="utf-8")
        assert "flask" in text
