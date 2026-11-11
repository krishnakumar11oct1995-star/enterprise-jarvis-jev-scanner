"""Conflict Radar Evaluator and Rule Orchestrator for Project Jarvis."""

from __future__ import annotations
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from jarvis.config import (
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
)
from jarvis.graph.models import Node, Edge, Conflict, ScanRun
from jarvis.graph.engine import DependencyGraphEngine
from jarvis.radar.rules import (
    BaseRuleEvaluator,
    RecursionRuleEvaluator,
    RaceConditionRuleEvaluator,
    GovernorLimitLoopRuleEvaluator,
    CalloutAfterDMLRuleEvaluator,
    CrossCloudContractRuleEvaluator,
    MultipleTriggersRuleEvaluator,
    SemanticDuplicateFieldRuleEvaluator,
    ParentLockContentionRuleEvaluator,
    OrphanedMetadataRuleEvaluator,
)


class ConflictRadarEvaluator:
    """Orchestrates conflict detection across all architectural rules and integrates memory enrichment."""

    def __init__(
        self,
        engine: DependencyGraphEngine,
        memory_bridge: Optional[Any] = None,
    ):
        self.engine = engine
        self.memory_bridge = memory_bridge
        self.evaluators: List[BaseRuleEvaluator] = [
            RecursionRuleEvaluator(),
            RaceConditionRuleEvaluator(),
            GovernorLimitLoopRuleEvaluator(),
            CalloutAfterDMLRuleEvaluator(),
            CrossCloudContractRuleEvaluator(),
            MultipleTriggersRuleEvaluator(),
            SemanticDuplicateFieldRuleEvaluator(),
            ParentLockContentionRuleEvaluator(),
            OrphanedMetadataRuleEvaluator(),
        ]

    def register_evaluator(self, evaluator: BaseRuleEvaluator) -> None:
        self.evaluators.append(evaluator)

    def evaluate(
        self,
        run_id: Optional[str] = None,
        target_path: str = "workspace",
        severity_filter: Optional[str] = None,
    ) -> Tuple[ScanRun, List[Conflict]]:
        start_time = time.time()
        active_run_id = run_id or f"scan_{uuid.uuid4().hex[:10]}"

        detected: List[Conflict] = []
        for evaluator in self.evaluators:
            try:
                results = evaluator.evaluate(self.engine)
                for conf in results:
                    conf.run_id = active_run_id
                detected.extend(results)
            except Exception as e:
                # Log or handle evaluator error gracefully
                pass

        # Enrich conflicts via Memory Bridge if available
        if self.memory_bridge is not None:
            try:
                self.memory_bridge.enrich_conflicts(detected)
            except Exception:
                pass

        # Severity filter if provided
        if severity_filter:
            sev = severity_filter.upper()
            if sev == SEVERITY_CRITICAL:
                filtered = [c for c in detected if c.severity == SEVERITY_CRITICAL]
            elif sev == SEVERITY_WARNING:
                filtered = [c for c in detected if c.severity in (SEVERITY_CRITICAL, SEVERITY_WARNING)]
            else:
                filtered = detected
        else:
            filtered = detected

        duration_ms = int((time.time() - start_time) * 1000)

        # Count severities
        crit_count = sum(1 for c in detected if c.severity == SEVERITY_CRITICAL)
        warn_count = sum(1 for c in detected if c.severity == SEVERITY_WARNING)
        info_count = sum(1 for c in detected if c.severity == SEVERITY_INFO)

        status = "FAILED" if crit_count > 0 else ("WARNING" if warn_count > 0 else "PASSED")

        counts = self.engine.counts()
        scan_run = ScanRun(
            run_id=active_run_id,
            target_path=target_path,
            total_nodes=counts.get("nodes", 0),
            total_edges=counts.get("edges", 0),
            critical_count=crit_count,
            warning_count=warn_count,
            info_count=info_count,
            duration_ms=duration_ms,
            status=status,
        )

        # Persist run and conflicts in DB
        self.engine.db.record_scan_run(scan_run)
        self.engine.db.record_conflicts(detected)

        return scan_run, filtered
