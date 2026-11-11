"""Conflict Radar Rules Engine for Project Jarvis.

Implements all 9 architectural conflict rules:
- RULE-REC-001 (Recursion)
- RULE-RACE-002 (Race Condition between Trigger & Flow)
- RULE-GOV-003 (SOQL/DML in loops)
- RULE-GOV-004 (Callout after DML)
- RULE-CONTR-005 (Cross-cloud breaking changes SF -> MuleSoft / Snowflake)
- RULE-ORDER-006 (Multiple triggers on same SObject)
- RULE-SCHEMA-007 (Semantic duplicate fields)
- RULE-LOCK-008 (Parent Record Lock Contention)
- RULE-DEAD-009 (Dead code / orphaned components)
"""

from __future__ import annotations
from abc import ABC, abstractmethod
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from jarvis.config import (
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
    NodeTypes,
    EdgeTypes,
    Systems,
)
from jarvis.graph.models import Node, Edge, Conflict
from jarvis.graph.engine import DependencyGraphEngine


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def normalize_field_stem(field_name: str) -> str:
    """Normalizes field name for semantic duplicate comparison."""
    name = field_name.replace("__c", "").replace("__C", "").lower()
    name = re.sub(r'[^a-z0-9]', '', name)
    # Synonyms
    synonyms = {
        "client": "customer",
        "mobile": "phone",
        "cell": "phone",
        "zipcode": "zip",
        "postalcode": "zip",
        "postal": "zip",
    }
    for old, new in synonyms.items():
        name = name.replace(old, new)
    return name


class BaseRuleEvaluator(ABC):
    """Base class for Conflict Radar rule evaluators."""

    rule_id: str
    category: str
    severity: str
    name: str

    @abstractmethod
    def evaluate(self, engine: DependencyGraphEngine) -> List[Conflict]:
        """Evaluates graph and returns detected conflicts."""
        pass


class RecursionRuleEvaluator(BaseRuleEvaluator):
    """RULE-REC-001: Direct/Indirect DML Infinite Recursion."""

    rule_id = "RULE-REC-001"
    category = "RECURSION"
    severity = SEVERITY_CRITICAL
    name = "Direct/Indirect DML Infinite Recursion"

    def evaluate(self, engine: DependencyGraphEngine) -> List[Conflict]:
        conflicts: List[Conflict] = []
        all_edges = engine.get_edges()

        # Build execution causality graph:
        # 1. INVOKES / CALLS: Source -> Target
        # 2. WRITES / UPDATES_FIELD: Source -> Target (Entity updates SObject)
        # 3. TRIGGERS_ON: Target -> Source (Updating SObject executes Trigger/Flow)
        adj: Dict[str, Set[str]] = {}
        all_nodes = set()

        for e in all_edges:
            if e.relationship in (EdgeTypes.INVOKES, EdgeTypes.CALLS, EdgeTypes.WRITES):
                adj.setdefault(e.source_id, set()).add(e.target_id)
                all_nodes.add(e.source_id)
                all_nodes.add(e.target_id)
            elif e.relationship == EdgeTypes.UPDATES_FIELD:
                # Target is field, map field's parent object if applicable
                field_node = engine.get_node(e.target_id)
                parent_id = field_node.parent_id if field_node else None
                if not parent_id and "." in e.target_id:
                    parts = e.target_id.split(".")
                    parent_id = f"salesforce.object.{parts[-2]}" if len(parts) >= 2 else None
                if parent_id:
                    adj.setdefault(e.source_id, set()).add(parent_id)
                    all_nodes.add(e.source_id)
                    all_nodes.add(parent_id)
            elif e.relationship == EdgeTypes.TRIGGERS_ON:
                # Causal direction: SObject update activates Trigger/Flow
                adj.setdefault(e.target_id, set()).add(e.source_id)
                # Also allow direct Trigger -> Object connection
                adj.setdefault(e.source_id, set()).add(e.target_id)
                all_nodes.add(e.source_id)
                all_nodes.add(e.target_id)

        # Detect cycles in causal graph
        cycles: List[List[str]] = []
        visited_globally = set()
        path: List[str] = []
        path_set = set()

        def dfs(u: str):
            path.append(u)
            path_set.add(u)

            for v in adj.get(u, set()):
                if len(path) > 12:
                    continue
                if v in path_set:
                    idx = path.index(v)
                    cycle = path[idx:] + [v]
                    # Filter cycles: must contain at least 2 distinct nodes (not just Object <-> Trigger)
                    distinct_non_obj = [n for n in cycle[:-1] if "object" not in n]
                    if len(set(cycle[:-1])) >= 3 or len(distinct_non_obj) >= 2:
                        # Canonical cycle
                        from jarvis.graph.traversal import _canonical_cycle
                        canon = _canonical_cycle(cycle)
                        if canon not in [tuple(c) for c in cycles]:
                            cycles.append(list(canon))
                elif v not in visited_globally:
                    dfs(v)

            path.pop()
            path_set.remove(u)

        for n in sorted(all_nodes):
            if n not in visited_globally:
                dfs(n)
                visited_globally.add(n)

        for cycle in cycles:
            # Check if any component in the cycle has a static recursion guard
            has_guard = False
            for node_id in cycle:
                node = engine.get_node(node_id)
                if node and node.metadata.get("has_recursion_guard"):
                    has_guard = True
                    break

            if not has_guard:
                # Format friendly cycle path
                path_names = []
                for n_id in cycle:
                    n = engine.get_node(n_id)
                    path_names.append(n.name if n else n_id.split(".")[-1])

                cycle_str = " -> ".join(path_names)
                # Choose primary node: prefer trigger or class
                primary = cycle[0]
                for nid in cycle:
                    if "trigger" in nid or "class" in nid:
                        primary = nid
                        break

                conflicts.append(Conflict(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    primary_node_id=primary,
                    secondary_node_id=cycle[-2] if len(cycle) > 2 else cycle[1],
                    cycle_path=cycle,
                    message=(
                        f"Detected potential infinite recursion loop: {cycle_str}. "
                        "The execution path contains mutating operations across related objects "
                        "without static recursion guards."
                    ),
                    context_data={"cycle": cycle, "cycle_names": path_names},
                ))

        return conflicts


class RaceConditionRuleEvaluator(BaseRuleEvaluator):
    """RULE-RACE-002: Apex Trigger & Flow Mutating Same SObject Field."""

    rule_id = "RULE-RACE-002"
    category = "RACE_CONDITION"
    severity = SEVERITY_CRITICAL
    name = "Apex Trigger & Flow Mutating Same SObject Field"

    def evaluate(self, engine: DependencyGraphEngine) -> List[Conflict]:
        conflicts: List[Conflict] = []

        # Find all SObjects
        objects = engine.get_nodes(system=Systems.SALESFORCE, node_type=NodeTypes.SF_OBJECT)
        obj_names = {o.name for o in objects}

        # Also collect object names from triggers or flows
        all_triggers = engine.get_nodes(system=Systems.SALESFORCE, node_type=NodeTypes.APEX_TRIGGER)
        all_flows = engine.get_nodes(system=Systems.SALESFORCE, node_type=NodeTypes.SF_FLOW)

        for t in all_triggers:
            target = t.metadata.get("target_object")
            if target:
                obj_names.add(target)
        for f in all_flows:
            target = f.metadata.get("target_object")
            if target:
                obj_names.add(target)

        for obj_name in obj_names:
            triggers = [
                t for t in all_triggers
                if t.metadata.get("target_object") == obj_name or any(
                    e.target_id.endswith(obj_name) for e in engine.get_edges(source_id=t.id, relationship=EdgeTypes.TRIGGERS_ON)
                )
            ]
            flows = [
                f for f in all_flows
                if f.metadata.get("target_object") == obj_name or any(
                    e.target_id.endswith(obj_name) for e in engine.get_edges(source_id=f.id, relationship=EdgeTypes.TRIGGERS_ON)
                )
            ]

            if not triggers or not flows:
                continue

            for t in triggers:
                for f in flows:
                    # Check if they share trigger events (e.g. before update)
                    t_events = set(t.metadata.get("events", []))
                    f_events = set(f.metadata.get("events", []))

                    # Normalize events
                    t_norm = {e.replace(" ", "_").lower() for e in t_events}
                    f_norm = {e.replace(" ", "_").lower() for e in f_events}
                    overlapping_events = t_norm.intersection(f_norm)

                    # Check fields updated by trigger
                    t_updates = {
                        e.target_id.split(".")[-1]
                        for e in engine.get_edges(source_id=t.id, relationship=EdgeTypes.UPDATES_FIELD)
                    }
                    # Also check classes invoked by trigger for field updates
                    for call_edge in engine.get_edges(source_id=t.id, relationship=EdgeTypes.INVOKES):
                        for f_edge in engine.get_edges(source_id=call_edge.target_id, relationship=EdgeTypes.UPDATES_FIELD):
                            t_updates.add(f_edge.target_id.split(".")[-1])

                    # Check fields updated by flow
                    f_updates = {
                        e.target_id.split(".")[-1]
                        for e in engine.get_edges(source_id=f.id, relationship=EdgeTypes.UPDATES_FIELD)
                    }

                    # Case-insensitive matching for shared fields
                    t_updates_map = {fld.lower(): fld for fld in t_updates}
                    f_updates_map = {fld.lower(): fld for fld in f_updates}
                    shared_lower = set(t_updates_map.keys()).intersection(set(f_updates_map.keys()))
                    shared_fields = {t_updates_map[k] for k in shared_lower}
                    if shared_fields:
                        for field in sorted(shared_fields):
                            conflicts.append(Conflict(
                                rule_id=self.rule_id,
                                severity=self.severity,
                                primary_node_id=t.id,
                                secondary_node_id=f.id,
                                message=(
                                    f"Race condition detected on '{obj_name}.{field}': Both Apex Trigger '{t.name}' "
                                    f"and Record-Triggered Flow '{f.name}' mutate this field. "
                                    "Salesforce order of execution is non-deterministic between Flows and Triggers."
                                ),
                                context_data={
                                    "sobject": obj_name,
                                    "field": field,
                                    "trigger": t.name,
                                    "flow": f.name,
                                    "events": list(overlapping_events) or list(t_norm | f_norm),
                                },
                            ))
                    elif overlapping_events and (t_updates or f_updates):
                        # Both update the same object on identical event
                        conflicts.append(Conflict(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            primary_node_id=t.id,
                            secondary_node_id=f.id,
                            message=(
                                f"Concurrency hazard on '{obj_name}': Trigger '{t.name}' and Flow '{f.name}' "
                                f"both execute on event {sorted(list(overlapping_events))} and perform record updates. "
                                "May produce race conditions or unexpected rollbacks."
                            ),
                            context_data={
                                "sobject": obj_name,
                                "trigger": t.name,
                                "flow": f.name,
                                "events": list(overlapping_events),
                            },
                        ))

        return conflicts


class GovernorLimitLoopRuleEvaluator(BaseRuleEvaluator):
    """RULE-GOV-003: SOQL / DML Inside Loop Iterations."""

    rule_id = "RULE-GOV-003"
    category = "GOVERNOR_LIMIT"
    severity = SEVERITY_CRITICAL
    name = "SOQL / DML Inside Loop Iterations"

    def evaluate(self, engine: DependencyGraphEngine) -> List[Conflict]:
        conflicts: List[Conflict] = []
        nodes = engine.get_nodes(system=Systems.SALESFORCE)

        for node in nodes:
            if node.type in (NodeTypes.APEX_CLASS, NodeTypes.APEX_TRIGGER):
                meta = node.metadata or {}
                if meta.get("soql_in_loop") or meta.get("dml_in_loop"):
                    details = meta.get("loop_details", [])
                    detail_msgs = []
                    for d in details:
                        line = d.get("line")
                        hdr = d.get("header")
                        hazards = []
                        if d.get("has_soql"):
                            hazards.append("SOQL query")
                        if d.get("has_dml"):
                            hazards.append("DML operation")
                        detail_msgs.append(f"Line {line} ({hdr}): {', '.join(hazards)}")

                    msg_suffix = " | ".join(detail_msgs) if detail_msgs else "SOQL/DML in loop detected"
                    conflicts.append(Conflict(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        primary_node_id=node.id,
                        message=(
                            f"Governor limit hazard in '{node.name}': Loop contains nested SOQL/DML statements. "
                            f"Violates 100 SOQL / 150 DML limits under bulk execution. ({msg_suffix})"
                        ),
                        context_data={"loop_details": details},
                    ))

        return conflicts


class CalloutAfterDMLRuleEvaluator(BaseRuleEvaluator):
    """RULE-GOV-004: Synchronous Callout Following Uncommitted DML."""

    rule_id = "RULE-GOV-004"
    category = "GOVERNOR_LIMIT"
    severity = SEVERITY_CRITICAL
    name = "Synchronous Callout Following Uncommitted DML"

    def evaluate(self, engine: DependencyGraphEngine) -> List[Conflict]:
        conflicts: List[Conflict] = []
        nodes = engine.get_nodes(system=Systems.SALESFORCE)

        for node in nodes:
            if node.type in (NodeTypes.APEX_CLASS, NodeTypes.APEX_TRIGGER):
                meta = node.metadata or {}
                if meta.get("callout_after_dml"):
                    details = meta.get("callout_details", [])
                    conflicts.append(Conflict(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        primary_node_id=node.id,
                        message=(
                            f"Synchronous Callout Following Uncommitted DML in '{node.name}'. "
                            "Salesforce runtime will throw System.CalloutException: "
                            "'You have uncommitted work pending. Please commit or rollback before calling out'."
                        ),
                        context_data={"callout_details": details},
                    ))

        return conflicts


class CrossCloudContractRuleEvaluator(BaseRuleEvaluator):
    """RULE-CONTR-005: Cross-Cloud Contract Breaking Change."""

    rule_id = "RULE-CONTR-005"
    category = "CONTRACT"
    severity = SEVERITY_CRITICAL
    name = "Cross-Cloud Contract Breaking Change"

    def evaluate(self, engine: DependencyGraphEngine) -> List[Conflict]:
        conflicts: List[Conflict] = []

        # Find all edges from MuleSoft or Snowflake referencing Salesforce fields
        all_edges = engine.get_edges()
        sf_fields = {
            f.id: f for f in engine.get_nodes(system=Systems.SALESFORCE, node_type=NodeTypes.SF_FIELD)
        }
        sf_field_names = {f.name: f for f in sf_fields.values()}

        # Also get all SF object names to know if parent object exists
        sf_objects = {
            o.name: o for o in engine.get_nodes(system=Systems.SALESFORCE, node_type=NodeTypes.SF_OBJECT)
        }

        for edge in all_edges:
            source_node = engine.get_node(edge.source_id)
            if not source_node:
                continue

            # Check if MuleSoft or Snowflake references a Salesforce field
            if source_node.system in (Systems.MULESOFT, Systems.SNOWFLAKE):
                if edge.target_id.startswith("salesforce.field."):
                    field_ref = edge.target_id.replace("salesforce.field.", "")
                    # field_ref could be Order.Tax_Amount__c or Tax_Amount__c
                    # Check if target field actually exists in schema (case-insensitive)
                    ref_lower = field_ref.lower()
                    target_lower = edge.target_id.lower()
                    sf_fields_lower = {k.lower() for k in sf_fields.keys()}
                    sf_names_lower = {k.lower() for k in sf_field_names.keys()}
                    field_exists = (
                        target_lower in sf_fields_lower
                        or ref_lower in sf_names_lower
                        or any(f.endswith(f".{ref_lower}") or f.split(".")[-1] == ref_lower for f in sf_fields_lower)
                    )

                    # Only flag contract break if we have harvested Salesforce schema nodes
                    if sf_fields and not field_exists:
                        conflicts.append(Conflict(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            primary_node_id=source_node.id,
                            secondary_node_id=edge.target_id,
                            message=(
                                f"Cross-Cloud Contract Breaking Change: '{source_node.name}' ({source_node.system}) "
                                f"references Salesforce field '{field_ref}', but this field is missing or was renamed "
                                "in the Salesforce schema. Ingestion pipelines and transforms will fail at runtime."
                            ),
                            context_data={
                                "consumer_system": source_node.system,
                                "consumer_component": source_node.name,
                                "missing_field": field_ref,
                                "file_path": source_node.file_path,
                            },
                        ))

        return conflicts


class MultipleTriggersRuleEvaluator(BaseRuleEvaluator):
    """RULE-ORDER-006: Multiple Triggers on Same SObject."""

    rule_id = "RULE-ORDER-006"
    category = "RACE_CONDITION"
    severity = SEVERITY_WARNING
    name = "Multiple Triggers on Same SObject"

    def evaluate(self, engine: DependencyGraphEngine) -> List[Conflict]:
        conflicts: List[Conflict] = []
        triggers = engine.get_nodes(system=Systems.SALESFORCE, node_type=NodeTypes.APEX_TRIGGER)

        # Group triggers by target object
        by_object: Dict[str, List[Node]] = {}
        for t in triggers:
            target = t.metadata.get("target_object")
            if not target:
                # Check outgoing TRIGGERS_ON edge
                edges = engine.get_edges(source_id=t.id, relationship=EdgeTypes.TRIGGERS_ON)
                if edges:
                    target = edges[0].target_id.split(".")[-1]
            if target:
                by_object.setdefault(target, []).append(t)

        for obj_name, trig_list in by_object.items():
            if len(trig_list) > 1:
                names = [t.name for t in trig_list]
                conflicts.append(Conflict(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    primary_node_id=trig_list[0].id,
                    secondary_node_id=trig_list[1].id,
                    message=(
                        f"Multiple Apex Triggers ({len(trig_list)}) defined on SObject '{obj_name}': {', '.join(names)}. "
                        "Salesforce does not guarantee trigger execution order. Consolidate into One-Trigger-Per-Object pattern."
                    ),
                    context_data={"sobject": obj_name, "triggers": names},
                ))

        return conflicts


class SemanticDuplicateFieldRuleEvaluator(BaseRuleEvaluator):
    """RULE-SCHEMA-007: Semantic Duplicate Custom Fields."""

    rule_id = "RULE-SCHEMA-007"
    category = "SCHEMA"
    severity = SEVERITY_WARNING
    name = "Semantic Duplicate Custom Fields"

    def evaluate(self, engine: DependencyGraphEngine) -> List[Conflict]:
        conflicts: List[Conflict] = []
        fields = engine.get_nodes(system=Systems.SALESFORCE, node_type=NodeTypes.SF_FIELD)

        # Group by parent SObject
        by_parent: Dict[str, List[Node]] = {}
        for f in fields:
            parent = f.parent_id or (f.name.split(".")[0] if "." in f.name else "Unknown")
            by_parent.setdefault(parent, []).append(f)

        seen_pairs = set()

        for parent, field_list in by_parent.items():
            n = len(field_list)
            for i in range(n):
                for j in range(i + 1, n):
                    f1 = field_list[i]
                    f2 = field_list[j]
                    pair_key = tuple(sorted([f1.id, f2.id]))
                    if pair_key in seen_pairs:
                        continue

                    name1 = f1.metadata.get("field_name") or f1.name.split(".")[-1]
                    name2 = f2.metadata.get("field_name") or f2.name.split(".")[-1]

                    stem1 = normalize_field_stem(name1)
                    stem2 = normalize_field_stem(name2)
                    dist = levenshtein_distance(stem1, stem2)

                    # Trigger if stem match or Levenshtein distance <= 1
                    is_duplicate = (stem1 == stem2) or (dist <= 1 and min(len(stem1), len(stem2)) > 4)

                    if is_duplicate:
                        seen_pairs.add(pair_key)
                        conflicts.append(Conflict(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            primary_node_id=f1.id,
                            secondary_node_id=f2.id,
                            message=(
                                f"Semantic duplicate custom fields on '{parent}': '{name1}' and '{name2}' "
                                f"(similarity edit distance: {dist}). Consolidate onto a single canonical field."
                            ),
                            context_data={
                                "parent": parent,
                                "field1": name1,
                                "field2": name2,
                                "distance": dist,
                            },
                        ))

        return conflicts


class ParentLockContentionRuleEvaluator(BaseRuleEvaluator):
    """RULE-LOCK-008: High-Volume Parent Record Lock Contention."""

    rule_id = "RULE-LOCK-008"
    category = "PERFORMANCE"
    severity = SEVERITY_WARNING
    name = "High-Volume Parent Record Lock Contention"

    def evaluate(self, engine: DependencyGraphEngine) -> List[Conflict]:
        conflicts: List[Conflict] = []
        # Flag batches updating high-volume child records with parent lookups
        batches = [
            n for n in engine.get_nodes(system=Systems.SALESFORCE, node_type=NodeTypes.APEX_CLASS)
            if n.metadata.get("is_batch")
        ]

        for b in batches:
            writes = engine.get_edges(source_id=b.id, relationship=EdgeTypes.WRITES)
            reads = engine.get_edges(source_id=b.id, relationship=EdgeTypes.READS)
            # If batch updates child records and reads common parents
            if len(writes) >= 1 and len(reads) >= 1:
                meta = b.metadata or {}
                if meta.get("high_concurrency") or meta.get("parallel_batches"):
                    conflicts.append(Conflict(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        primary_node_id=b.id,
                        message=(
                            f"Batch job '{b.name}' operates concurrently across child records sharing parent relationships, "
                            "risking UNABLE_TO_LOCK_ROW lock contention."
                        ),
                        context_data={"batch": b.name},
                    ))

        return conflicts


class OrphanedMetadataRuleEvaluator(BaseRuleEvaluator):
    """RULE-DEAD-009: Orphaned Metadata / Unreferenced Component."""

    rule_id = "RULE-DEAD-009"
    category = "HYGIENE"
    severity = SEVERITY_INFO
    name = "Orphaned Metadata / Unreferenced Component"

    def evaluate(self, engine: DependencyGraphEngine) -> List[Conflict]:
        conflicts: List[Conflict] = []
        orphans = engine.get_orphaned_nodes()

        for node in orphans:
            conflicts.append(Conflict(
                rule_id=self.rule_id,
                severity=self.severity,
                primary_node_id=node.id,
                message=(
                    f"Orphaned component: '{node.name}' ({node.type}) has zero incoming references "
                    "and is not marked as a public entry point. Review for retirement to minimize technical debt."
                ),
                context_data={"component": node.name, "type": node.type, "file_path": node.file_path},
            ))

        return conflicts
