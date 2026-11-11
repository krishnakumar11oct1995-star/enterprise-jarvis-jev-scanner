"""Core Dependency Graph Engine for Project Jarvis."""

from __future__ import annotations
from typing import Any, Optional, List, Dict, Set

from jarvis.config import DEFAULT_DB_PATH, NodeTypes, EdgeTypes
from jarvis.graph.models import Node, Edge, Rule, Conflict, ScanRun, BlastRadiusResult
from jarvis.graph.db import JarvisGraphDB
from jarvis.graph.traversal import GraphTraversal


class DependencyGraphEngine:
    """High-level dependency graph management, querying, and relationship analysis."""

    def __init__(self, db: Optional[JarvisGraphDB] = None, db_path: Optional[str] = None):
        if db is not None:
            self.db = db
        elif db_path is not None:
            self.db = JarvisGraphDB(db_path)
        else:
            self.db = JarvisGraphDB(DEFAULT_DB_PATH)
        self.traversal = GraphTraversal(self.db)

    # Node operations
    def add_node(
        self,
        node_id: str,
        system: str,
        node_type: str,
        name: str,
        parent_id: Optional[str] = None,
        file_path: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Node:
        node = Node(
            id=node_id,
            system=system,
            type=node_type,
            name=name,
            parent_id=parent_id,
            file_path=file_path,
            metadata=metadata or {},
        )
        self.db.upsert_node(node)
        return node

    def add_nodes(self, nodes: list[Node]) -> None:
        self.db.upsert_nodes(nodes)

    def get_node(self, node_id: str) -> Optional[Node]:
        return self.db.get_node(node_id)

    def get_nodes(self, system: Optional[str] = None, node_type: Optional[str] = None) -> list[Node]:
        return self.db.get_nodes(system=system, type=node_type)

    def search_nodes(self, query: str, limit: int = 20) -> list[Node]:
        return self.db.search_nodes(query, limit=limit)

    # Edge operations
    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        properties: Optional[dict[str, Any]] = None,
    ) -> Edge:
        edge = Edge(
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
            properties=properties or {},
        )
        self.db.upsert_edge(edge)
        return edge

    def add_edges(self, edges: list[Edge]) -> None:
        self.db.upsert_edges(edges)

    def get_edges(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relationship: Optional[str] = None,
    ) -> list[Edge]:
        return self.db.get_edges(source_id=source_id, target_id=target_id, relationship=relationship)

    # Traversal & Analysis
    def blast_radius(
        self,
        component_id: str,
        depth: int = 5,
        direction: str = "downstream",
    ) -> BlastRadiusResult:
        return self.traversal.blast_radius(component_id, max_depth=depth, direction=direction)

    def detect_cycles(
        self,
        allowed_relationships: Optional[Set[str]] = None,
        max_cycle_length: int = 10,
    ) -> List[List[str]]:
        return self.traversal.find_cycles(
            allowed_relationships=allowed_relationships,
            max_cycle_length=max_cycle_length,
        )

    def detect_sccs(self, allowed_relationships: Optional[Set[str]] = None) -> List[List[str]]:
        return self.traversal.find_strongly_connected_components(allowed_relationships)

    # Domain Queries
    def get_triggers_for_object(self, object_name: str) -> list[Node]:
        """Find all apex triggers associated with an SObject."""
        obj_id = f"salesforce.object.{object_name}"
        edges = self.get_edges(target_id=obj_id, relationship=EdgeTypes.TRIGGERS_ON)
        triggers = []
        for e in edges:
            n = self.get_node(e.source_id)
            if n and n.type == NodeTypes.APEX_TRIGGER:
                triggers.append(n)
        return triggers

    def get_flows_for_object(self, object_name: str) -> list[Node]:
        """Find all flows triggering on an SObject."""
        obj_id = f"salesforce.object.{object_name}"
        edges = self.get_edges(target_id=obj_id, relationship=EdgeTypes.TRIGGERS_ON)
        flows = []
        for e in edges:
            n = self.get_node(e.source_id)
            if n and n.type == NodeTypes.SF_FLOW:
                flows.append(n)
        return flows

    def get_field_writers(self, field_id: str) -> list[tuple[Node, Edge]]:
        """Find all nodes that write/update a specific field."""
        edges = self.get_edges(target_id=field_id)
        writers = []
        for e in edges:
            if e.relationship in (EdgeTypes.WRITES, EdgeTypes.UPDATES_FIELD):
                n = self.get_node(e.source_id)
                if n:
                    writers.append((n, e))
        return writers

    def get_field_readers(self, field_id: str) -> list[tuple[Node, Edge]]:
        """Find all nodes that read a specific field."""
        edges = self.get_edges(target_id=field_id)
        readers = []
        for e in edges:
            if e.relationship in (EdgeTypes.READS, EdgeTypes.READS_FIELD):
                n = self.get_node(e.source_id)
                if n:
                    readers.append((n, e))
        return readers

    def get_orphaned_nodes(self) -> list[Node]:
        """Find nodes with zero in-degree that are not entry points."""
        candidate_types = {
            NodeTypes.APEX_CLASS,
            NodeTypes.SF_FLOW,
            NodeTypes.MULE_ENDPOINT,
            NodeTypes.SNOW_TABLE,
        }
        all_nodes = self.get_nodes()
        orphans = []
        for n in all_nodes:
            if n.type not in candidate_types:
                continue
            # Check metadata if it's marked as entry point or test class
            meta = n.metadata or {}
            if meta.get("is_entry_point") or meta.get("is_test") or meta.get("is_trigger"):
                continue
            in_edges = self.db.get_incoming_edges(n.id)
            if len(in_edges) == 0:
                orphans.append(n)
        return orphans

    def counts(self) -> dict[str, int]:
        return self.db.counts()

    def clear(self) -> None:
        self.db.clear()
