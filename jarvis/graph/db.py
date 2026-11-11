"""SQLite Database persistence for Project Jarvis Dependency Graph."""

from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Optional

from jarvis.config import (
    DEFAULT_DB_PATH,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
)
from jarvis.graph.models import Node, Edge, Rule, Conflict, ScanRun

DEFAULT_RULES = [
    Rule(
        rule_id="RULE-REC-001",
        category="RECURSION",
        severity=SEVERITY_CRITICAL,
        name="Direct/Indirect DML Infinite Recursion",
        description=(
            "A trigger or flow execution path updates records that fire downstream automations "
            "looping back to the original entity without static recursion guards."
        ),
        remediation_guide=(
            "Introduce static set tracking (e.g., RecursionGuard.hasRun(id)) or migrate post-save "
            "mutations to before-save flows/triggers."
        ),
    ),
    Rule(
        rule_id="RULE-RACE-002",
        category="RACE_CONDITION",
        severity=SEVERITY_CRITICAL,
        name="Apex Trigger & Flow Mutating Same SObject Field",
        description=(
            "Both an Apex Trigger and a Record-Triggered Flow execute on the same SObject and "
            "modify identical or interdependent fields, risking non-deterministic interleaving."
        ),
        remediation_guide=(
            "Consolidate business logic into a single automation framework (Trigger Handler or Flow Orchestrator)."
        ),
    ),
    Rule(
        rule_id="RULE-GOV-003",
        category="GOVERNOR_LIMIT",
        severity=SEVERITY_CRITICAL,
        name="SOQL / DML Inside Loop Iterations",
        description=(
            "A SOQL query or DML statement is nested inside a loop construct (for, while, do-while), "
            "risking immediate breach of 100 SOQL / 150 DML transaction governor limits."
        ),
        remediation_guide=(
            "Query data in bulk outside the loop into a Map or List, and buffer DML records into a collection."
        ),
    ),
    Rule(
        rule_id="RULE-GOV-004",
        category="GOVERNOR_LIMIT",
        severity=SEVERITY_CRITICAL,
        name="Synchronous Callout Following Uncommitted DML",
        description=(
            "A synchronous HTTP callout occurs after uncommitted DML in the same transaction, "
            "causing a runtime CalloutException (You have uncommitted work pending)."
        ),
        remediation_guide=(
            "Execute the callout prior to DML state changes or decouple the callout into an asynchronous Queueable job."
        ),
    ),
    Rule(
        rule_id="RULE-CONTR-005",
        category="CONTRACT",
        severity=SEVERITY_CRITICAL,
        name="Cross-Cloud Contract Breaking Change",
        description=(
            "A Salesforce field is deleted, renamed, or modified, breaking dependent MuleSoft integration "
            "flows or Snowflake ingestion DDLs."
        ),
        remediation_guide=(
            "Synchronize changes across Salesforce, MuleSoft, and Snowflake schemas before deprecating source fields."
        ),
    ),
    Rule(
        rule_id="RULE-ORDER-006",
        category="RACE_CONDITION",
        severity=SEVERITY_WARNING,
        name="Multiple Triggers on Same SObject",
        description=(
            "Multiple apex triggers exist on the same SObject. Salesforce does not guarantee trigger execution order."
        ),
        remediation_guide=(
            "Consolidate into the One-Trigger-Per-Object pattern delegating to a Trigger Handler framework."
        ),
    ),
    Rule(
        rule_id="RULE-SCHEMA-007",
        category="SCHEMA",
        severity=SEVERITY_WARNING,
        name="Semantic Duplicate Custom Fields",
        description=(
            "Multiple active custom fields on the same object share high string similarity or identical label stems."
        ),
        remediation_guide=(
            "Deprecate duplicate fields and standardize integrations on a single canonical field."
        ),
    ),
    Rule(
        rule_id="RULE-LOCK-008",
        category="PERFORMANCE",
        severity=SEVERITY_WARNING,
        name="High-Volume Parent Record Lock Contention",
        description=(
            "High-concurrency batch or integration jobs update child records that share the same parent, risking UNABLE_TO_LOCK_ROW."
        ),
        remediation_guide=(
            "Use serial processing, partition batches by parent ID, or minimize parent record lock windows."
        ),
    ),
    Rule(
        rule_id="RULE-DEAD-009",
        category="HYGIENE",
        severity=SEVERITY_INFO,
        name="Orphaned Metadata / Unreferenced Component",
        description=(
            "An apex class, flow, endpoint, or table has zero incoming references and is not an entry point."
        ),
        remediation_guide=(
            "Review component for retirement to reduce code sprawl and technical debt."
        ),
    ),
]


from contextlib import contextmanager


class JarvisGraphDB:
    """Manages SQLite storage for nodes, edges, rules, scan runs, and conflicts."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        if db_path == ":memory:":
            self.db_path = ":memory:"
            self._is_memory = True
            self._mem_conn = sqlite3.connect(":memory:")
            self._mem_conn.execute("PRAGMA foreign_keys = ON;")
            self._mem_conn.row_factory = sqlite3.Row
        else:
            self._is_memory = False
            self.db_path = str(Path(db_path).resolve())
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        if self._is_memory:
            yield self._mem_conn
        else:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def close(self) -> None:
        """Flushes WAL and closes any pending resources."""
        if self._is_memory:
            try:
                self._mem_conn.close()
            except Exception:
                pass
        else:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                conn.close()
            except Exception:
                pass

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            c = conn.cursor()
            # 1. Nodes
            c.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    system TEXT NOT NULL,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    parent_id TEXT,
                    file_path TEXT,
                    metadata_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (parent_id) REFERENCES nodes(id) ON DELETE SET NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_nodes_system_type ON nodes(system, type)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id)")

            # 2. Edges
            c.execute("""
                CREATE TABLE IF NOT EXISTS edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relationship TEXT NOT NULL,
                    properties_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE,
                    UNIQUE(source_id, target_id, relationship)
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_edges_relationship ON edges(relationship)")

            # 3. Rules
            c.execute("""
                CREATE TABLE IF NOT EXISTS rules (
                    rule_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    remediation_guide TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1
                )
            """)

            # 4. Scan Runs
            c.execute("""
                CREATE TABLE IF NOT EXISTS scan_runs (
                    run_id TEXT PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    target_path TEXT NOT NULL,
                    total_nodes INTEGER DEFAULT 0,
                    total_edges INTEGER DEFAULT 0,
                    critical_count INTEGER DEFAULT 0,
                    warning_count INTEGER DEFAULT 0,
                    info_count INTEGER DEFAULT 0,
                    duration_ms INTEGER DEFAULT 0,
                    status TEXT NOT NULL
                )
            """)

            # 5. Detected Conflicts
            c.execute("""
                CREATE TABLE IF NOT EXISTS detected_conflicts (
                    conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    primary_node_id TEXT NOT NULL,
                    secondary_node_id TEXT,
                    cycle_path TEXT,
                    message TEXT NOT NULL,
                    context_data_json TEXT,
                    historical_rca_summary TEXT,
                    historical_conv_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (run_id) REFERENCES scan_runs(run_id) ON DELETE CASCADE,
                    FOREIGN KEY (rule_id) REFERENCES rules(rule_id),
                    FOREIGN KEY (primary_node_id) REFERENCES nodes(id) ON DELETE CASCADE
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_conflicts_run ON detected_conflicts(run_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conflicts_rule ON detected_conflicts(rule_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conflicts_severity ON detected_conflicts(severity)")

            # 6. Nodes FTS5
            try:
                c.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                        id,
                        name,
                        type,
                        system,
                        file_path,
                        content='nodes',
                        content_rowid='rowid'
                    )
                """)
            except Exception:
                pass  # Fallback if FTS5 not built with triggers

            # Seed default rules
            for rule in DEFAULT_RULES:
                c.execute("""
                    INSERT OR IGNORE INTO rules (rule_id, category, severity, name, description, remediation_guide, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    rule.rule_id,
                    rule.category,
                    rule.severity,
                    rule.name,
                    rule.description,
                    rule.remediation_guide,
                    1 if rule.is_active else 0,
                ))
            conn.commit()

    def upsert_node(self, node: Node) -> None:
        self.upsert_nodes([node])

    def upsert_nodes(self, nodes: list[Node]) -> None:
        if not nodes:
            return
        with self._get_connection() as conn:
            c = conn.cursor()
            for node in nodes:
                meta_json = json.dumps(node.metadata) if node.metadata else "{}"
                c.execute("""
                    INSERT INTO nodes (id, system, type, name, parent_id, file_path, metadata_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET
                        system=excluded.system,
                        type=excluded.type,
                        name=excluded.name,
                        parent_id=excluded.parent_id,
                        file_path=excluded.file_path,
                        metadata_json=excluded.metadata_json,
                        updated_at=CURRENT_TIMESTAMP
                """, (
                    node.id,
                    node.system,
                    node.type,
                    node.name,
                    node.parent_id,
                    node.file_path,
                    meta_json,
                ))
            conn.commit()

    def get_node(self, node_id: str) -> Optional[Node]:
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id, system, type, name, parent_id, file_path, metadata_json FROM nodes WHERE id = ?", (node_id,))
            row = c.fetchone()
            if row:
                return Node.from_row(tuple(row))
        return None

    def get_nodes(self, system: Optional[str] = None, type: Optional[str] = None) -> list[Node]:
        query = "SELECT id, system, type, name, parent_id, file_path, metadata_json FROM nodes WHERE 1=1"
        params: list[Any] = []
        if system:
            query += " AND system = ?"
            params.append(system)
        if type:
            query += " AND type = ?"
            params.append(type)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(query, params)
            return [Node.from_row(tuple(r)) for r in c.fetchall()]

    def search_nodes(self, query: str, limit: int = 20) -> list[Node]:
        with self._get_connection() as conn:
            c = conn.cursor()
            # Try FTS5
            try:
                clean_q = '"' + query.replace('"', '""') + '"'
                c.execute("""
                    SELECT n.id, n.system, n.type, n.name, n.parent_id, n.file_path, n.metadata_json
                    FROM nodes_fts f
                    JOIN nodes n ON f.rowid = n.rowid
                    WHERE nodes_fts MATCH ?
                    LIMIT ?
                """, (clean_q, limit))
                results = [Node.from_row(tuple(r)) for r in c.fetchall()]
                if results:
                    return results
            except Exception:
                pass
            # Fallback to LIKE
            like_str = f"%{query}%"
            c.execute("""
                SELECT id, system, type, name, parent_id, file_path, metadata_json
                FROM nodes
                WHERE id LIKE ? OR name LIKE ? OR file_path LIKE ?
                LIMIT ?
            """, (like_str, like_str, like_str, limit))
            return [Node.from_row(tuple(r)) for r in c.fetchall()]

    def upsert_edge(self, edge: Edge) -> None:
        self.upsert_edges([edge])

    def upsert_edges(self, edges: list[Edge]) -> None:
        if not edges:
            return
        with self._get_connection() as conn:
            c = conn.cursor()
            for edge in edges:
                # Ensure foreign key integrity by auto-creating placeholder nodes if unharvested
                for n_id in (edge.source_id, edge.target_id):
                    c.execute("SELECT 1 FROM nodes WHERE id = ?", (n_id,))
                    if not c.fetchone():
                        sys_guess = "salesforce" if "salesforce" in n_id or "apex" in n_id else ("mulesoft" if "mule" in n_id else ("snowflake" if "snow" in n_id else "external"))
                        c.execute("""
                            INSERT OR IGNORE INTO nodes (id, system, type, name, metadata_json)
                            VALUES (?, ?, 'EXTERNAL_REF', ?, '{"stub": true}')
                        """, (n_id, sys_guess, n_id.split(".")[-1]))

                props_json = json.dumps(edge.properties) if edge.properties else "{}"
                c.execute("""
                    INSERT INTO edges (source_id, target_id, relationship, properties_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(source_id, target_id, relationship) DO UPDATE SET
                        properties_json=excluded.properties_json
                """, (
                    edge.source_id,
                    edge.target_id,
                    edge.relationship,
                    props_json,
                ))
            conn.commit()

    def get_edges(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relationship: Optional[str] = None,
    ) -> list[Edge]:
        query = "SELECT id, source_id, target_id, relationship, properties_json FROM edges WHERE 1=1"
        params: list[Any] = []
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        if target_id:
            query += " AND target_id = ?"
            params.append(target_id)
        if relationship:
            query += " AND relationship = ?"
            params.append(relationship)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(query, params)
            return [Edge.from_row(tuple(r)) for r in c.fetchall()]

    def get_outgoing_edges(self, node_id: str) -> list[Edge]:
        return self.get_edges(source_id=node_id)

    def get_incoming_edges(self, node_id: str) -> list[Edge]:
        return self.get_edges(target_id=node_id)

    def record_scan_run(self, scan_run: ScanRun) -> None:
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO scan_runs (
                    run_id, target_path, total_nodes, total_edges,
                    critical_count, warning_count, info_count, duration_ms, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                scan_run.run_id,
                scan_run.target_path,
                scan_run.total_nodes,
                scan_run.total_edges,
                scan_run.critical_count,
                scan_run.warning_count,
                scan_run.info_count,
                scan_run.duration_ms,
                scan_run.status,
            ))
            conn.commit()

    def record_conflicts(self, conflicts: list[Conflict]) -> None:
        if not conflicts:
            return
        with self._get_connection() as conn:
            c = conn.cursor()
            for conf in conflicts:
                cycle_str = None
                if conf.cycle_path:
                    if isinstance(conf.cycle_path, list):
                        cycle_str = " -> ".join(conf.cycle_path)
                    else:
                        cycle_str = str(conf.cycle_path)
                ctx_json = json.dumps(conf.context_data) if conf.context_data else "{}"
                c.execute("""
                    INSERT INTO detected_conflicts (
                        run_id, rule_id, severity, primary_node_id, secondary_node_id,
                        cycle_path, message, context_data_json, historical_rca_summary,
                        historical_conv_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    conf.run_id,
                    conf.rule_id,
                    conf.severity,
                    conf.primary_node_id,
                    conf.secondary_node_id,
                    cycle_str,
                    conf.message,
                    ctx_json,
                    conf.historical_rca_summary,
                    conf.historical_conv_id,
                ))
            conn.commit()

    def get_conflicts(self, run_id: Optional[str] = None) -> list[Conflict]:
        query = """
            SELECT conflict_id, run_id, rule_id, severity, primary_node_id,
                   secondary_node_id, cycle_path, message, context_data_json,
                   historical_rca_summary, historical_conv_id
            FROM detected_conflicts
        """
        params: list[Any] = []
        if run_id:
            query += " WHERE run_id = ?"
            params.append(run_id)
        query += " ORDER BY conflict_id ASC"
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(query, params)
            conflicts = []
            for row in c.fetchall():
                ctx = {}
                if row["context_data_json"]:
                    try:
                        ctx = json.loads(row["context_data_json"])
                    except Exception:
                        pass
                conflicts.append(Conflict(
                    conflict_id=row["conflict_id"],
                    run_id=row["run_id"],
                    rule_id=row["rule_id"],
                    severity=row["severity"],
                    primary_node_id=row["primary_node_id"],
                    secondary_node_id=row["secondary_node_id"],
                    cycle_path=row["cycle_path"],
                    message=row["message"],
                    context_data=ctx,
                    historical_rca_summary=row["historical_rca_summary"],
                    historical_conv_id=row["historical_conv_id"],
                ))
            return conflicts

    def get_rules(self) -> list[Rule]:
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT rule_id, category, severity, name, description, remediation_guide, is_active FROM rules WHERE is_active = 1")
            return [Rule.from_row(tuple(r)) for r in c.fetchall()]

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT rule_id, category, severity, name, description, remediation_guide, is_active FROM rules WHERE rule_id = ?", (rule_id,))
            row = c.fetchone()
            if row:
                return Rule.from_row(tuple(row))
        return None

    def counts(self) -> dict[str, int]:
        with self._get_connection() as conn:
            c = conn.cursor()
            nodes_count = c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edges_count = c.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            rules_count = c.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
            conflicts_count = c.execute("SELECT COUNT(*) FROM detected_conflicts").fetchone()[0]
            runs_count = c.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0]
            return {
                "nodes": nodes_count,
                "edges": edges_count,
                "rules": rules_count,
                "conflicts": conflicts_count,
                "scan_runs": runs_count,
            }

    def clear(self) -> None:
        """Clear all nodes, edges, scan runs, and conflicts (preserves rules)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM detected_conflicts;")
            conn.execute("DELETE FROM scan_runs;")
            conn.execute("DELETE FROM edges;")
            conn.execute("DELETE FROM nodes;")
            conn.commit()
