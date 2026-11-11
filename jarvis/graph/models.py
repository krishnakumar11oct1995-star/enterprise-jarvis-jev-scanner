"""Data models for Project Jarvis Graph Engine."""

from __future__ import annotations
from dataclasses import dataclass, field
import json
from typing import Any, Optional


@dataclass
class Node:
    id: str
    system: str
    type: str
    name: str
    parent_id: Optional[str] = None
    file_path: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "system": self.system,
            "type": self.type,
            "name": self.name,
            "parent_id": self.parent_id,
            "file_path": self.file_path,
            "metadata": self.metadata,
        }

    @classmethod
    def from_row(cls, row: tuple) -> Node:
        # id, system, type, name, parent_id, file_path, metadata_json
        meta = {}
        if len(row) > 6 and row[6]:
            try:
                meta = json.loads(row[6]) if isinstance(row[6], str) else row[6]
            except Exception:
                meta = {}
        return cls(
            id=row[0],
            system=row[1],
            type=row[2],
            name=row[3],
            parent_id=row[4],
            file_path=row[5],
            metadata=meta,
        )


@dataclass
class Edge:
    source_id: str
    target_id: str
    relationship: str
    properties: dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship": self.relationship,
            "properties": self.properties,
        }

    @classmethod
    def from_row(cls, row: tuple) -> Edge:
        # id, source_id, target_id, relationship, properties_json
        props = {}
        if len(row) > 4 and row[4]:
            try:
                props = json.loads(row[4]) if isinstance(row[4], str) else row[4]
            except Exception:
                props = {}
        return cls(
            id=row[0],
            source_id=row[1],
            target_id=row[2],
            relationship=row[3],
            properties=props,
        )


@dataclass
class Rule:
    rule_id: str
    category: str
    severity: str
    name: str
    description: str
    remediation_guide: str
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "name": self.name,
            "description": self.description,
            "remediation_guide": self.remediation_guide,
            "is_active": self.is_active,
        }

    @classmethod
    def from_row(cls, row: tuple) -> Rule:
        return cls(
            rule_id=row[0],
            category=row[1],
            severity=row[2],
            name=row[3],
            description=row[4],
            remediation_guide=row[5],
            is_active=bool(row[6]) if len(row) > 6 else True,
        )


@dataclass
class Conflict:
    rule_id: str
    severity: str
    primary_node_id: str
    message: str
    secondary_node_id: Optional[str] = None
    cycle_path: Optional[list[str] | str] = None
    context_data: dict[str, Any] = field(default_factory=dict)
    historical_rca_summary: Optional[str] = None
    historical_conv_id: Optional[str] = None
    run_id: str = ""
    conflict_id: Optional[int] = None

    @property
    def cycle_path_list(self) -> list[str]:
        if not self.cycle_path:
            return []
        if isinstance(self.cycle_path, list):
            return self.cycle_path
        if isinstance(self.cycle_path, str):
            try:
                parsed = json.loads(self.cycle_path)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
            return [x.strip() for x in self.cycle_path.split("->")]
        return []

    def to_dict(self) -> dict[str, Any]:
        cycle = self.cycle_path_list if self.cycle_path else None
        return {
            "conflict_id": self.conflict_id,
            "run_id": self.run_id,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "primary_node_id": self.primary_node_id,
            "secondary_node_id": self.secondary_node_id,
            "cycle_path": cycle,
            "message": self.message,
            "context_data": self.context_data,
            "historical_rca_summary": self.historical_rca_summary,
            "historical_conv_id": self.historical_conv_id,
        }


@dataclass
class ScanRun:
    run_id: str
    target_path: str
    total_nodes: int = 0
    total_edges: int = 0
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    duration_ms: int = 0
    status: str = "PASSED"
    timestamp: str = ""


@dataclass
class BlastRadiusResult:
    root_node_id: str
    max_depth: int
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    depth_map: dict[str, int] = field(default_factory=dict)
    systems_affected: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_node_id": self.root_node_id,
            "max_depth": self.max_depth,
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "systems_affected": sorted(list(self.systems_affected)),
            "depth_distribution": {
                d: sum(1 for v in self.depth_map.values() if v == d)
                for d in set(self.depth_map.values())
            },
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }
