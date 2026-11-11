"""Graph traversal, cycle detection, and blast radius analysis for Project Jarvis."""

from __future__ import annotations
from collections import deque
from typing import Any, Optional, Set, List, Dict

from jarvis.graph.models import Node, Edge, BlastRadiusResult
from jarvis.graph.db import JarvisGraphDB


class GraphTraversal:
    """Provides high-performance traversal algorithms over Jarvis graph."""

    def __init__(self, db: JarvisGraphDB):
        self.db = db

    def blast_radius(
        self,
        start_node_id: str,
        max_depth: int = 5,
        direction: str = "downstream",
    ) -> BlastRadiusResult:
        """
        Computes transitive blast radius of a component up to max_depth.
        direction: 'downstream' (following outgoing edges),
                   'upstream' (following incoming edges),
                   'both' (bidirectional).
        """
        root_node = self.db.get_node(start_node_id)
        if not root_node:
            # If not found directly, try finding by name or search
            matching = self.db.search_nodes(start_node_id, limit=1)
            if matching:
                root_node = matching[0]
                start_node_id = root_node.id
            else:
                return BlastRadiusResult(root_node_id=start_node_id, max_depth=max_depth)

        visited_nodes: Dict[str, Node] = {root_node.id: root_node}
        visited_edges: List[Edge] = []
        depth_map: Dict[str, int] = {root_node.id: 0}
        systems_affected: Set[str] = {root_node.system}

        # BFS queue: (node_id, current_depth)
        queue = deque([(root_node.id, 0)])
        seen_edge_keys = set()

        while queue:
            curr_id, curr_depth = queue.popleft()
            if curr_depth >= max_depth:
                continue

            edges_to_follow = []
            if direction in ("downstream", "both"):
                for edge in self.db.get_outgoing_edges(curr_id):
                    edges_to_follow.append((edge, edge.target_id))
            if direction in ("upstream", "both"):
                for edge in self.db.get_incoming_edges(curr_id):
                    edges_to_follow.append((edge, edge.source_id))

            for edge, next_id in edges_to_follow:
                edge_key = (edge.source_id, edge.target_id, edge.relationship)
                if edge_key not in seen_edge_keys:
                    seen_edge_keys.add(edge_key)
                    visited_edges.append(edge)

                if next_id not in depth_map:
                    depth_map[next_id] = curr_depth + 1
                    next_node = self.db.get_node(next_id)
                    if next_node:
                        visited_nodes[next_id] = next_node
                        systems_affected.add(next_node.system)
                    queue.append((next_id, curr_depth + 1))

        return BlastRadiusResult(
            root_node_id=root_node.id,
            max_depth=max_depth,
            nodes=list(visited_nodes.values()),
            edges=visited_edges,
            depth_map=depth_map,
            systems_affected=systems_affected,
        )

    def find_cycles(
        self,
        allowed_relationships: Optional[Set[str]] = None,
        max_cycle_length: int = 10,
    ) -> List[List[str]]:
        """
        Finds directed cycles in the graph using DFS cycle detection.
        Optionally filters edges by allowed relationships.
        Returns a list of cycle paths where each path is [n1, n2, ..., nk, n1].
        """
        all_edges = self.db.get_edges()
        if allowed_relationships:
            edges = [e for e in all_edges if e.relationship in allowed_relationships]
        else:
            edges = all_edges

        # Build adjacency list: node -> set of target nodes
        adj: Dict[str, Set[str]] = {}
        all_nodes = set()
        for e in edges:
            adj.setdefault(e.source_id, set()).add(e.target_id)
            all_nodes.add(e.source_id)
            all_nodes.add(e.target_id)

        cycles: List[List[str]] = []
        visited_globally = set()
        path: List[str] = []
        path_set = set()

        def dfs(u: str):
            path.append(u)
            path_set.add(u)

            for v in adj.get(u, set()):
                if len(path) > max_cycle_length:
                    continue
                if v in path_set:
                    # Found a cycle from v to u back to v
                    idx = path.index(v)
                    cycle = path[idx:] + [v]
                    # Normalize cycle representation to prevent duplicates with different rotations
                    canonical = _canonical_cycle(cycle)
                    if canonical not in [tuple(c) for c in cycles]:
                        cycles.append(list(canonical))
                elif v not in visited_globally:
                    dfs(v)

            path.pop()
            path_set.remove(u)

        for node in sorted(all_nodes):
            if node not in visited_globally:
                dfs(node)
                visited_globally.add(node)

        return cycles

    def find_strongly_connected_components(
        self,
        allowed_relationships: Optional[Set[str]] = None,
    ) -> List[List[str]]:
        """
        Tarjan's algorithm for finding Strongly Connected Components (SCCs).
        Returns SCCs with size > 1 (which are cycles/mutually recursive clusters).
        """
        all_edges = self.db.get_edges()
        if allowed_relationships:
            edges = [e for e in all_edges if e.relationship in allowed_relationships]
        else:
            edges = all_edges

        adj: Dict[str, List[str]] = {}
        all_nodes = set()
        for e in edges:
            adj.setdefault(e.source_id, []).append(e.target_id)
            all_nodes.add(e.source_id)
            all_nodes.add(e.target_id)

        index = 0
        indices: Dict[str, int] = {}
        lowlink: Dict[str, int] = {}
        stack: List[str] = []
        on_stack: Set[str] = set()
        sccs: List[List[str]] = []

        def strongconnect(v: str):
            nonlocal index
            indices[v] = index
            lowlink[v] = index
            index += 1
            stack.append(v)
            on_stack.add(v)

            for w in adj.get(v, []):
                if w not in indices:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], indices[w])

            if lowlink[v] == indices[v]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    scc.append(w)
                    if w == v:
                        break
                if len(scc) > 1:
                    sccs.append(scc)

        for node in all_nodes:
            if node not in indices:
                strongconnect(node)

        return sccs


def _canonical_cycle(cycle: List[str]) -> tuple[str, ...]:
    """Given a cycle [a, b, c, a], produces canonical representation starting at minimum element."""
    nodes = cycle[:-1]
    if not nodes:
        return tuple(cycle)
    min_idx = nodes.index(min(nodes))
    rotated = nodes[min_idx:] + nodes[:min_idx]
    return tuple(rotated + [rotated[0]])
