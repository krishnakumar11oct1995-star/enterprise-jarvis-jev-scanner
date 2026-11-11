"""JSON exporter for CI/CD pipeline integration."""

from __future__ import annotations
import json
from typing import Any, Dict, List

from jarvis.graph.models import Conflict, ScanRun, BlastRadiusResult


def export_scan_json(scan_run: ScanRun, conflicts: List[Conflict]) -> str:
    """Exports scan run and conflict records as structured JSON."""
    data = {
        "scan_run": {
            "run_id": scan_run.run_id,
            "target_path": scan_run.target_path,
            "status": scan_run.status,
            "duration_ms": scan_run.duration_ms,
            "total_nodes": scan_run.total_nodes,
            "total_edges": scan_run.total_edges,
            "critical_count": scan_run.critical_count,
            "warning_count": scan_run.warning_count,
            "info_count": scan_run.info_count,
        },
        "conflicts": [c.to_dict() for c in conflicts],
    }
    return json.dumps(data, indent=2)


def export_blast_radius_json(result: BlastRadiusResult) -> str:
    """Exports blast radius results as JSON."""
    return json.dumps(result.to_dict(), indent=2)
