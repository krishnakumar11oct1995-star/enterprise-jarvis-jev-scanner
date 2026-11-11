"""Re-export and alias for Jarvis Graph Store."""

from jarvis.graph.db import JarvisGraphDB, DEFAULT_RULES
from jarvis.graph.models import Node, Edge, Rule, Conflict, ScanRun, BlastRadiusResult

GraphStore = JarvisGraphDB

__all__ = [
    "JarvisGraphDB",
    "GraphStore",
    "DEFAULT_RULES",
    "Node",
    "Edge",
    "Rule",
    "Conflict",
    "ScanRun",
    "BlastRadiusResult",
]
