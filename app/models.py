"""Core data models and contracts for Salesforce Jarvis PC Application."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, List, Optional, Tuple


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class PollerState(str, Enum):
    IDLE = "IDLE"
    POLLING = "POLLING"
    EVALUATING = "EVALUATING"
    ERROR = "ERROR"
    DISCONNECTED = "DISCONNECTED"


class EventTopic(str, Enum):
    SCAN_STARTED = "scan_started"
    SCAN_COMPLETED = "scan_completed"
    ORG_STATUS = "org_status"
    TIER1_ALERT = "tier1_alert"
    TIER2_ALERT = "tier2_alert"
    TIER3_ALERT = "tier3_alert"
    TIER4_ALERT = "tier4_alert"
    VOICE_SPEAK = "voice_speak"
    VOICE_MUTE = "voice_mute"
    HUD_TOGGLE = "hud_toggle"
    TRIGGER_SCAN = "trigger_scan"
    TRIGGER_BRIEFING = "trigger_briefing"
    SYSTEM_SHUTDOWN = "system_shutdown"


@dataclass(frozen=True)
class ConflictItem:
    rule_id: str
    severity: Severity
    primary_node_id: str
    message: str
    secondary_node_id: Optional[str] = None
    cycle_path: Optional[str] = None
    remediation: Optional[str] = None
    historical_rca: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value if isinstance(self.severity, Severity) else str(self.severity),
            "primary_node_id": self.primary_node_id,
            "message": self.message,
            "secondary_node_id": self.secondary_node_id,
            "cycle_path": self.cycle_path,
            "remediation": self.remediation,
            "historical_rca": self.historical_rca,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class ScanResult:
    run_id: str
    timestamp: float
    duration_ms: float
    total_conflicts: int
    critical_count: int
    warning_count: int
    info_count: int
    conflicts: Tuple[ConflictItem, ...]
    is_clean: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "total_conflicts": self.total_conflicts,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "is_clean": self.is_clean,
        }


@dataclass(frozen=True)
class OrgStatus:
    org_name: str
    username: str
    is_connected: bool
    state: PollerState
    last_poll_time: float = field(default_factory=time.time)
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_name": self.org_name,
            "username": self.username,
            "is_connected": self.is_connected,
            "state": self.state.value if isinstance(self.state, PollerState) else str(self.state),
            "last_poll_time": self.last_poll_time,
            "error_message": self.error_message,
        }


@dataclass(order=True)
class VoiceMessage:
    priority: int  # 0 = Highest (CRITICAL), 10 = Normal, 20 = Low
    text: str = field(compare=False)
    timestamp: float = field(default_factory=time.time, compare=False)
    source: str = field(default="radar", compare=False)


@dataclass(frozen=True)
class BatchApexErrorEventRecord:
    async_apex_job_id: str
    job_scope_record_ids: Tuple[str, ...]
    exception_type: str
    message: str
    stack_trace: str
    phase: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "async_apex_job_id": self.async_apex_job_id,
            "job_scope_record_ids": list(self.job_scope_record_ids),
            "exception_type": self.exception_type,
            "message": self.message,
            "stack_trace": self.stack_trace,
            "phase": self.phase,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class CronTriggerInfo:
    job_id: str
    cron_job_detail_name: str
    state: str
    next_fire_time: Optional[str] = None
    previous_fire_time: Optional[str] = None
    times_triggered: int = 0
    time_zone: Optional[str] = None
    is_missed_or_late: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "cron_job_detail_name": self.cron_job_detail_name,
            "state": self.state,
            "next_fire_time": self.next_fire_time,
            "previous_fire_time": self.previous_fire_time,
            "times_triggered": self.times_triggered,
            "time_zone": self.time_zone,
            "is_missed_or_late": self.is_missed_or_late,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class BulkApiJobInfo:
    job_id: str
    operation: str
    object_name: str
    state: str
    records_processed: int = 0
    records_failed: int = 0
    total_processing_time_ms: int = 0
    created_date: Optional[str] = None
    job_type: str = "Classic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "operation": self.operation,
            "object_name": self.object_name,
            "state": self.state,
            "records_processed": self.records_processed,
            "records_failed": self.records_failed,
            "total_processing_time_ms": self.total_processing_time_ms,
            "created_date": self.created_date,
            "job_type": self.job_type,
        }


@dataclass(frozen=True)
class CertExpiryInfo:
    cert_name: str
    expiration_date: str
    days_until_expiry: int
    is_expired: bool
    org_name: str
    developer_name: Optional[str] = None
    key_size: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cert_name": self.cert_name,
            "developer_name": self.developer_name,
            "expiration_date": self.expiration_date,
            "days_until_expiry": self.days_until_expiry,
            "is_expired": self.is_expired,
            "org_name": self.org_name,
            "key_size": self.key_size,
        }


@dataclass(frozen=True)
class SetupAuditTrailRecord:
    id: str
    action: str
    section: Optional[str]
    created_date: str
    created_by_name: str
    display: str
    delegate_user: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "section": self.section,
            "created_date": self.created_date,
            "created_by_name": self.created_by_name,
            "display": self.display,
            "delegate_user": self.delegate_user,
        }


@dataclass(frozen=True)
class CodeCoverageInfo:
    org_wide_coverage_pct: float
    classes_evaluated: int = 0
    num_below_75_pct: int = 0
    uncovered_lines_total: int = 0
    top_uncovered_classes: Tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_wide_coverage_pct": self.org_wide_coverage_pct,
            "classes_evaluated": self.classes_evaluated,
            "num_below_75_pct": self.num_below_75_pct,
            "uncovered_lines_total": self.uncovered_lines_total,
            "top_uncovered_classes": list(self.top_uncovered_classes),
        }


@dataclass(frozen=True)
class AuthSessionUser:
    session_id: str
    user_id: str
    username: str
    user_type: str
    source_ip: str
    login_type: str
    session_type: str
    created_date: str
    last_modified_date: str
    name: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "username": self.username,
            "name": self.name,
            "user_type": self.user_type,
            "source_ip": self.source_ip,
            "login_type": self.login_type,
            "session_type": self.session_type,
            "created_date": self.created_date,
            "last_modified_date": self.last_modified_date,
        }


@dataclass(frozen=True)
class SnowflakeReconInfo:
    object_name: str
    sf_record_count: int
    sf_max_modstamp: Optional[str]
    snowflake_record_count: int
    snowflake_max_modstamp: Optional[str]
    variance_count: int
    is_reconciled: bool
    last_checked: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_name": self.object_name,
            "sf_record_count": self.sf_record_count,
            "sf_max_modstamp": self.sf_max_modstamp,
            "snowflake_record_count": self.snowflake_record_count,
            "snowflake_max_modstamp": self.snowflake_max_modstamp,
            "variance_count": self.variance_count,
            "is_reconciled": self.is_reconciled,
            "last_checked": self.last_checked,
        }


@dataclass(frozen=True)
class DataQualityProbe:
    probe_name: str
    target_object: str
    field_name: str
    total_records: int
    null_or_invalid_count: int
    null_rate_pct: float
    status: Severity = Severity.INFO
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_name": self.probe_name,
            "target_object": self.target_object,
            "field_name": self.field_name,
            "total_records": self.total_records,
            "null_or_invalid_count": self.null_or_invalid_count,
            "null_rate_pct": self.null_rate_pct,
            "status": self.status.value if isinstance(self.status, Severity) else str(self.status),
            "message": self.message,
        }

