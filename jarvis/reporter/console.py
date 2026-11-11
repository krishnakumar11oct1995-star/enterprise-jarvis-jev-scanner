"""Terminal console reporter for Project Jarvis."""

from __future__ import annotations
import sys
from typing import List, Optional

from jarvis.config import SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO
from jarvis.graph.models import Conflict, ScanRun, BlastRadiusResult

# Try rich formatting if installed
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def print_scan_report(scan_run: ScanRun, conflicts: List[Conflict]) -> None:
    """Renders the scan run and conflicts to the console."""
    if HAS_RICH:
        console = Console()
        status_color = "red" if scan_run.status == "FAILED" else ("yellow" if scan_run.status == "WARNING" else "green")

        console.print(Panel(
            f"[bold {status_color}]PROJECT JARVIS ARCHITECTURAL SCAN: {scan_run.status}[/]\n"
            f"Run ID: [cyan]{scan_run.run_id}[/] | Duration: {scan_run.duration_ms}ms | Target: [dim]{scan_run.target_path}[/]\n"
            f"Graph: {scan_run.total_nodes} nodes, {scan_run.total_edges} edges\n"
            f"Violations: [red bold]{scan_run.critical_count} CRITICAL[/], "
            f"[yellow]{scan_run.warning_count} WARNING[/], "
            f"[blue]{scan_run.info_count} INFO[/]",
            title="Conflict Radar Quality Gate",
            border_style=status_color,
        ))

        if not conflicts:
            console.print("[green]✔ No architectural conflicts detected. Topology is clean![/]\n")
            return

        table = Table(title="Detected Architectural Conflicts & Hazards", show_lines=True)
        table.add_column("Rule ID", style="bold cyan", no_wrap=True)
        table.add_column("Severity", no_wrap=True)
        table.add_column("Component", style="bold")
        table.add_column("Details & Remediation")

        for conf in conflicts:
            sev_color = "red bold" if conf.severity == SEVERITY_CRITICAL else ("yellow" if conf.severity == SEVERITY_WARNING else "blue")
            details = conf.message
            if conf.cycle_path:
                details += f"\n[magenta bold]Cycle:[/] {conf.cycle_path}"
            if conf.historical_rca_summary:
                details += f"\n[green dim]★ {conf.historical_rca_summary}[/]"

            table.add_row(
                conf.rule_id,
                f"[{sev_color}]{conf.severity}[/]",
                conf.primary_node_id,
                details,
            )
        console.print(table)
        console.print()

    else:
        # Standard ASCII format
        print("=" * 80)
        print(f" PROJECT JARVIS ARCHITECTURAL SCAN: {scan_run.status}")
        print(f" Run ID: {scan_run.run_id} | Duration: {scan_run.duration_ms}ms | Target: {scan_run.target_path}")
        print(f" Graph: {scan_run.total_nodes} nodes, {scan_run.total_edges} edges")
        print(f" Violations: {scan_run.critical_count} CRITICAL, {scan_run.warning_count} WARNING, {scan_run.info_count} INFO")
        print("=" * 80)

        if not conflicts:
            print("  No architectural conflicts detected. Topology is clean!\n")
            return

        for i, c in enumerate(conflicts, 1):
            print(f"[{i}] [{c.severity}] {c.rule_id} on {c.primary_node_id}")
            print(f"    Message: {c.message}")
            if c.cycle_path:
                print(f"    Cycle:   {c.cycle_path}")
            if c.historical_rca_summary:
                print(f"    RCA Context: {c.historical_rca_summary}")
            print("-" * 80)


def print_blast_radius(result: BlastRadiusResult) -> None:
    """Renders blast radius traversal result."""
    if HAS_RICH:
        console = Console()
        table = Table(title=f"Blast Radius Analysis for '{result.root_node_id}' (Max Depth: {result.max_depth})", show_lines=True)
        table.add_column("Depth", style="bold yellow", width=6)
        table.add_column("Node ID", style="cyan", width=35)
        table.add_column("System", width=12)
        table.add_column("Type", width=14)
        table.add_column("Name", width=25)

        for node in sorted(result.nodes, key=lambda n: result.depth_map.get(n.id, 0)):
            d = result.depth_map.get(node.id, 0)
            table.add_row(str(d), node.id, node.system, node.type, node.name)

        console.print(table)
        console.print(f"[bold]Total Nodes Affected:[/] {len(result.nodes)} | [bold]Systems Affected:[/] {', '.join(sorted(result.systems_affected))}\n")
    else:
        print("=" * 80)
        print(f" Blast Radius for '{result.root_node_id}' (Depth: {result.max_depth})")
        print(f" Affected Nodes: {len(result.nodes)} | Affected Systems: {', '.join(sorted(result.systems_affected))}")
        print("=" * 80)
        for node in sorted(result.nodes, key=lambda n: result.depth_map.get(n.id, 0)):
            d = result.depth_map.get(node.id, 0)
            print(f" [Depth {d}] ({node.system} / {node.type}) {node.id}")
        print("-" * 80)
