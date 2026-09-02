"""Sequence-diagram derivation.

Derives ordered call chains ("sequences") from a merged
:class:`~wenuroute.models.RouteGraph`, suitable for rendering as UML-style
sequence diagrams. Unlike an unordered ego-network (see the focus-mode JS in
``graph.py``), each sequence is a real *path*: entry point -> ... -> terminal
step, in traversal order, with the edge label that connects each hop.

The traversal is bounded so it stays fast regardless of project size:
cycles are cut per-path (not globally forbidden), fan-out per entry point is
capped, and the total number of generated sequences is capped.
"""

from __future__ import annotations

from wenuroute.models import NodeKind, RouteGraph

# Edges that represent "flow of control" (something happens, something else
# follows). Structural/declarative edges (imports, defines, uses, contains)
# are deliberately excluded — including them would turn every module into a
# giant, meaningless fan-out instead of a narrative call chain.
_FLOW_EDGE_LABELS = {"calls", "executes", "triggers", "handles", "navigates", "submits"}

_ENTRY_KINDS = {NodeKind.UI_ELEMENT, NodeKind.EVENT, NodeKind.ENDPOINT}

MAX_DEPTH = 6
MAX_CHAINS_PER_ENTRY = 3
MAX_CHAINS = 40
# Raw generation runs to a higher budget than MAX_CHAINS so the two dedup
# passes below (see derive_sequences) have real duplicates to remove instead
# of the cap silently starving out entry points late in traversal order.
_RAW_CHAIN_BUDGET = MAX_CHAINS * 4


def _build_flow_adjacency(graph: RouteGraph) -> dict[str, list[tuple[str, str]]]:
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge in graph.edges:
        if edge.label not in _FLOW_EDGE_LABELS:
            continue
        if edge.source_id not in graph.nodes or edge.target_id not in graph.nodes:
            continue
        adjacency.setdefault(edge.source_id, []).append((edge.target_id, edge.label))
    for targets in adjacency.values():
        targets.sort(key=lambda t: t[0])
    return adjacency


def _dfs_chains(
    node_id: str,
    adjacency: dict[str, list[tuple[str, str]]],
    visited: set[str],
    depth: int,
) -> list[list[tuple[str, str | None]]]:
    """Return completed chains starting at *node_id*, as lists of (node_id, edge_label)."""
    outgoing = adjacency.get(node_id, [])
    if depth >= MAX_DEPTH or not outgoing:
        return [[(node_id, None)]]

    chains: list[list[tuple[str, str | None]]] = []
    for target_id, edge_label in outgoing[:MAX_CHAINS_PER_ENTRY]:
        if target_id in visited:
            # Cycle on this path: stop here rather than recursing forever.
            chains.append([(node_id, None), (target_id, edge_label)])
            continue
        sub_chains = _dfs_chains(target_id, adjacency, visited | {target_id}, depth + 1)
        for sub in sub_chains:
            chains.append([(node_id, None)] + [
                (nid, lbl if i > 0 else edge_label) for i, (nid, lbl) in enumerate(sub)
            ])
        if len(chains) >= MAX_CHAINS_PER_ENTRY:
            break

    return chains[:MAX_CHAINS_PER_ENTRY]


def _build_sequence(graph: RouteGraph, seq_id: str, steps: list[tuple[str, str | None]]) -> dict:
    step_dicts = []
    for node_id, edge_label in steps:
        node = graph.nodes[node_id]
        step = {
            "node_id": node.id,
            "label": node.label,
            "kind": node.kind.value,
            "file": node.file,
            "line": node.line,
        }
        if edge_label is not None:
            step["edge_label"] = edge_label
        step_dicts.append(step)

    title = " → ".join(s["label"] for s in step_dicts[:3])
    if len(step_dicts) > 3:
        title += " → …"

    return {
        "id": seq_id,
        "title": title,
        "entry_kind": step_dicts[0]["kind"] if step_dicts else "unknown",
        "origin_count": 1,
        "steps": step_dicts,
    }


def _drop_event_prefixed_duplicates(sequences: list[dict]) -> list[dict]:
    """Drop an EVENT-rooted sequence whose steps are exactly some other
    sequence's steps with its first (UI_ELEMENT) hop removed.

    ``_ENTRY_KINDS`` includes both UI_ELEMENT and EVENT because an EVENT can
    also be a legitimate standalone entry (e.g. a programmatically dispatched
    one) — but the common case is a UI_ELEMENT ``--triggers-->`` EVENT edge,
    which makes the EVENT node *also* qualify as an entry on its own,
    producing a second sequence that's just the first one minus its opening
    hop. That's not new information, just noise.
    """
    tails = {tuple(s["node_id"] for s in seq["steps"][1:]) for seq in sequences}
    return [
        seq for seq in sequences
        if not (seq["entry_kind"] == "event" and tuple(s["node_id"] for s in seq["steps"]) in tails)
    ]


def _merge_similar_origins(sequences: list[dict]) -> list[dict]:
    """Collapse sequences that differ only in *which* element started them.

    E.g. three different DOM elements all wired to the same ``onclick``
    handler calling the same function produce three sequences identical from
    the second step onward. Keep the first as a representative and fold the
    rest into its ``origin_count`` rather than listing near-duplicates.
    """
    merged: dict[tuple, dict] = {}
    result: list[dict] = []
    for seq in sequences:
        tail_key = tuple((s["label"], s.get("edge_label")) for s in seq["steps"][1:])
        if not tail_key:
            result.append(seq)
            continue
        existing = merged.get(tail_key)
        if existing is None:
            merged[tail_key] = seq
            result.append(seq)
        else:
            existing["origin_count"] += 1
    return result


def derive_sequences(graph: RouteGraph) -> list[dict]:
    """Derive a bounded list of call-chain sequences from *graph*.

    Each returned dict has shape:
    ``{"id", "title", "entry_kind", "origin_count", "steps": [{"node_id",
    "label", "kind", "file", "line", "edge_label"?}]}``. ``edge_label`` is
    present on every step except the first (it records the edge that led
    into that step). ``origin_count`` > 1 means this many near-duplicate
    sequences (same call chain, different triggering element) were folded
    into this one — see ``_merge_similar_origins``.
    """
    adjacency = _build_flow_adjacency(graph)

    entry_ids = [
        node.id
        for node in graph.nodes.values()
        if node.kind in _ENTRY_KINDS and node.id in adjacency
    ]
    entry_ids.sort(key=lambda nid: (graph.nodes[nid].file, graph.nodes[nid].line))

    sequences: list[dict] = []
    for entry_id in entry_ids:
        if len(sequences) >= _RAW_CHAIN_BUDGET:
            break
        for steps in _dfs_chains(entry_id, adjacency, {entry_id}, depth=0):
            if len(steps) < 2:
                continue  # an entry with no real hop isn't a sequence
            if len(sequences) >= _RAW_CHAIN_BUDGET:
                break
            sequences.append(_build_sequence(graph, f"seq:{len(sequences)}", steps))

    sequences = _drop_event_prefixed_duplicates(sequences)
    sequences = _merge_similar_origins(sequences)
    sequences = sequences[:MAX_CHAINS]
    for i, seq in enumerate(sequences):
        seq["id"] = f"seq:{i}"

    return sequences
