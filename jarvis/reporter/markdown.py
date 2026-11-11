"""GitHub-Flavored Markdown report generator for Project Jarvis."""

from __future__ import annotations
from typing import List, Optional

from jarvis.config import SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO
from jarvis.graph.models import Conflict, ScanRun, BlastRadiusResult


def generate_scan_markdown(scan_run: ScanRun, conflicts: List[Conflict]) -> str:
    """Generates an architectural audit report in Markdown."""
    lines = []
    lines.append("# Project Jarvis: Architecture & Conflict Radar Audit Report\n")

    # Status Alert
    if scan_run.status == "FAILED":
        lines.append("> [!CAUTION]\n> **Quality Gate Failed**: Critical architectural violations detected! Deployment blocked.")
    elif scan_run.status == "WARNING":
        lines.append("> [!WARNING]\n> **Quality Gate Passed with Warnings**: Non-critical architectural hazards detected.")
    else:
        lines.append("> [!NOTE]\n> **Quality Gate Passed**: Architecture is clean. No conflicting metadata patterns detected.")

    lines.append("\n## 1. Executive Summary\n")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| **Run ID** | `{scan_run.run_id}` |")
    lines.append(f"| **Target Path** | `{scan_run.target_path}` |")
    lines.append(f"| **Status** | **{scan_run.status}** |")
    lines.append(f"| **Scan Duration** | `{scan_run.duration_ms} ms` |")
    lines.append(f"| **Graph Nodes Analyzed** | `{scan_run.total_nodes}` |")
    lines.append(f"| **Graph Edges Traversed** | `{scan_run.total_edges}` |")
    lines.append(f"| **Critical Conflicts** | **{scan_run.critical_count}** |")
    lines.append(f"| **Warnings** | **{scan_run.warning_count}** |")
    lines.append(f"| **Hygiene / Info** | **{scan_run.info_count}** |\n")

    lines.append("## 2. Detected Architectural Conflicts\n")

    if not conflicts:
        lines.append("_No conflicts detected._\n")
    else:
        lines.append("| Rule ID | Severity | Component | Message | Historical Context |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for c in conflicts:
            rca_snippet = "None"
            if c.historical_rca_summary:
                rca_snippet = c.historical_rca_summary[:80] + "..."
            clean_msg = c.message.replace("\n", " ").replace("|", "\\|")
            lines.append(f"| `{c.rule_id}` | **{c.severity}** | `{c.primary_node_id}` | {clean_msg} | {rca_snippet} |")
        lines.append("\n")

        lines.append("## 3. Conflict Details & Remediation Plans\n")
        for i, c in enumerate(conflicts, 1):
            lines.append(f"### {i}. [{c.severity}] `{c.rule_id}`: {c.primary_node_id}\n")
            lines.append(f"- **Message:** {c.message}")
            if c.secondary_node_id:
                lines.append(f"- **Secondary Node:** `{c.secondary_node_id}`")
            if c.cycle_path:
                cycle_repr = " -> ".join(c.cycle_path_list) if c.cycle_path_list else str(c.cycle_path)
                lines.append(f"- **Detected Cycle Path:** `{cycle_repr}`")

            if c.historical_rca_summary:
                lines.append("\n#### Historical RCA Context (Antigravity Index)\n")
                lines.append(f"> [!TIP]\n> {c.historical_rca_summary}")
                if c.historical_conv_id:
                    lines.append(f">\n> **Conversation ID:** `{c.historical_conv_id}`")

            lines.append("\n---\n")

    return "\n".join(lines)


def generate_blast_radius_markdown(result: BlastRadiusResult) -> str:
    """Generates Markdown report for blast radius impact analysis."""
    lines = []
    lines.append(f"# Blast Radius Impact Analysis: `{result.root_node_id}`\n")
    lines.append(f"- **Max Depth Analyzed:** `{result.max_depth}` hops")
    lines.append(f"- **Total Nodes Affected:** `{len(result.nodes)}`")
    lines.append(f"- **Total Relationships:** `{len(result.edges)}`")
    lines.append(f"- **Systems Affected:** `{', '.join(sorted(result.systems_affected))}`\n")

    lines.append("## Downstream / Upstream Impact Topology\n")
    lines.append("| Depth | Node ID | System | Type | Name |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for node in sorted(result.nodes, key=lambda n: result.depth_map.get(n.id, 0)):
        d = result.depth_map.get(node.id, 0)
        lines.append(f"| {d} | `{node.id}` | {node.system} | `{node.type}` | {node.name} |")
    lines.append("\n")

    return "\n".join(lines)
