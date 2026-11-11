"""Configuration constants and defaults for Project Jarvis."""

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = str(BASE_DIR / "jarvis_graph.sqlite")

DEFAULT_INDEX_DIR = r"C:\Users\Krishna\Downloads\Antigravity Index"
DEFAULT_INDEX_DB = str(Path(DEFAULT_INDEX_DIR) / "index.sqlite")

# Exit Codes
EXIT_SUCCESS = 0       # Clean scan or only non-critical warnings
EXIT_CRITICAL = 1      # Failed quality gate due to CRITICAL conflict
EXIT_ERROR = 2         # Harvester, runtime, or syntax error

# Severities
SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

SEVERITY_LEVELS = [SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO]

# Node Types
class NodeTypes:
    SF_OBJECT = "SF_OBJECT"
    SF_FIELD = "SF_FIELD"
    APEX_CLASS = "APEX_CLASS"
    APEX_TRIGGER = "APEX_TRIGGER"
    SF_FLOW = "SF_FLOW"
    MULE_FLOW = "MULE_FLOW"
    MULE_ENDPOINT = "MULE_ENDPOINT"
    SNOW_TABLE = "SNOW_TABLE"
    SNOW_COLUMN = "SNOW_COLUMN"
    SNOW_PIPE = "SNOW_PIPE"
    SNOW_TASK = "SNOW_TASK"
    VALIDATION_RULE = "VALIDATION_RULE"
    BATCH_JOB = "BATCH_JOB"

# Edge Types
class EdgeTypes:
    READS = "READS"
    WRITES = "WRITES"
    INVOKES = "INVOKES"
    CALLS_OUT = "CALLS_OUT"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    TRIGGERS_ON = "TRIGGERS_ON"
    CALLS = "CALLS"
    UPDATES_FIELD = "UPDATES_FIELD"
    READS_FIELD = "READS_FIELD"
    INVOKES_FLOW = "INVOKES_FLOW"
    ENQUEUES_JOB = "ENQUEUES_JOB"
    INTEGRATES_WITH = "INTEGRATES_WITH"
    LOADS_TO = "LOADS_TO"
    SYNCED_FROM = "SYNCED_FROM"
    DEPENDS_ON = "DEPENDS_ON"

# Systems
class Systems:
    SALESFORCE = "salesforce"
    MULESOFT = "mulesoft"
    SNOWFLAKE = "snowflake"
