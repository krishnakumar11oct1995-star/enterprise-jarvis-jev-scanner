"""Historical Transcript Harvester for Project Jarvis.

Mines historical conversation turns and transcripts from Antigravity Index
to bootstrap the Dependency Graph with Krishna's real Salesforce components,
including Encounter__c, Patient_Insurance__c, YesterdayDenialSyncBatch,
and UpdateEncounterOwnerAndRoutingBatch.
"""

from __future__ import annotations
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from jarvis.config import (
    DEFAULT_INDEX_DIR,
    DEFAULT_INDEX_DB,
    NodeTypes,
    EdgeTypes,
    Systems,
)
from jarvis.graph.models import Node, Edge
from jarvis.harvester.base import BaseHarvester


class TranscriptHarvester(BaseHarvester):
    """Harvests architectural components from Antigravity Index transcripts & database."""

    def __init__(self, index_dir: str = DEFAULT_INDEX_DIR):
        self.index_dir = Path(index_dir)
        self.db_path = self.index_dir / "index.sqlite"

    def harvest(self, source: Optional[Union[str, Path]] = None) -> Tuple[List[Node], List[Edge]]:
        db_file = Path(source) if source and str(source).endswith(".sqlite") else self.db_path
        if not db_file.exists():
            return [], []

        nodes_map: Dict[str, Node] = {}
        edges_set: Set[Tuple[str, str, str, str]] = set()

        # Connect to index.sqlite
        try:
            conn = sqlite3.connect(str(db_file))
            c = conn.cursor()
            rows = c.execute("""
                SELECT id, conv_id, timestamp, user_prompt, solution_summary, files_touched, md_file
                FROM turns
            """).fetchall()
        except Exception:
            return [], []
        finally:
            conn.close()

        # Regex patterns for enterprise components
        custom_obj_regex = re.compile(r'\b([A-Z][A-Za-z0-9_]*__(?:c|mdt|e))\b')
        batch_class_regex = re.compile(r'\b([A-Z][A-Za-z0-9_]*Batch)\b')
        trigger_regex = re.compile(r'\b([A-Z][A-Za-z0-9_]*Trigger)\b')
        service_regex = re.compile(r'\b([A-Z][A-Za-z0-9_]*(?:Service|Handler|Helper|Controller|Util))\b')

        # Known foundational components to ensure are always indexed
        known_objects = ["Encounter__c", "Patient_Insurance__c", "Denial_Lines__c", "Account", "Contact", "Opportunity"]
        known_batches = ["YesterdayDenialSyncBatch", "UpdateEncounterOwnerAndRoutingBatch"]

        for obj in known_objects:
            obj_id = f"salesforce.object.{obj}"
            nodes_map[obj_id] = Node(
                id=obj_id,
                system=Systems.SALESFORCE,
                type=NodeTypes.SF_OBJECT,
                name=obj,
                metadata={"source": "antigravity_index_seed"},
            )

        for batch in known_batches:
            batch_id = f"apex.class.{batch}"
            nodes_map[batch_id] = Node(
                id=batch_id,
                system=Systems.SALESFORCE,
                type=NodeTypes.APEX_CLASS,
                name=batch,
                metadata={"is_batch": True, "source": "antigravity_index_seed"},
            )

        # Iterate through turns to extract mentions and relationships
        for row in rows:
            _, conv_id, ts, prompt, summary, files_touched, md_file = row
            text = f"{prompt or ''}\n{summary or ''}\n{files_touched or ''}"

            # Extract SObjects
            objs_in_turn = set(custom_obj_regex.findall(text))
            for obj in objs_in_turn:
                # Filter out obvious false positives like __c alone
                if len(obj) <= 4 or obj in ("List__c", "Test__c", "Object__c"):
                    continue
                obj_id = f"salesforce.object.{obj}"
                if obj_id not in nodes_map:
                    nodes_map[obj_id] = Node(
                        id=obj_id,
                        system=Systems.SALESFORCE,
                        type=NodeTypes.SF_OBJECT,
                        name=obj,
                        metadata={"source": "antigravity_transcript", "last_conv_id": conv_id},
                    )

            # Extract Batch classes
            batches_in_turn = set(batch_class_regex.findall(text))
            for batch in batches_in_turn:
                batch_id = f"apex.class.{batch}"
                if batch_id not in nodes_map:
                    nodes_map[batch_id] = Node(
                        id=batch_id,
                        system=Systems.SALESFORCE,
                        type=NodeTypes.APEX_CLASS,
                        name=batch,
                        metadata={"is_batch": True, "source": "antigravity_transcript", "last_conv_id": conv_id},
                    )

            # Extract Triggers
            triggers_in_turn = set(trigger_regex.findall(text))
            for trig in triggers_in_turn:
                trig_id = f"apex.trigger.{trig}"
                if trig_id not in nodes_map:
                    nodes_map[trig_id] = Node(
                        id=trig_id,
                        system=Systems.SALESFORCE,
                        type=NodeTypes.APEX_TRIGGER,
                        name=trig,
                        metadata={"source": "antigravity_transcript", "last_conv_id": conv_id},
                    )

            # Link Batches to Objects if co-occurring in the turn
            for batch in batches_in_turn:
                batch_id = f"apex.class.{batch}"
                for obj in objs_in_turn:
                    obj_id = f"salesforce.object.{obj}"
                    edges_set.add((batch_id, obj_id, EdgeTypes.READS, "TRANSCRIPT_CO_OCCURRENCE"))

            # Link Triggers to Objects
            for trig in triggers_in_turn:
                trig_id = f"apex.trigger.{trig}"
                for obj in objs_in_turn:
                    # e.g. EncounterTrigger with Encounter__c
                    base_name = trig.replace("Trigger", "")
                    if base_name in obj:
                        edges_set.add((trig_id, f"salesforce.object.{obj}", EdgeTypes.TRIGGERS_ON, "NAME_MATCH"))

        # Explicit known enterprise relationships
        edges_set.add(("apex.class.YesterdayDenialSyncBatch", "salesforce.object.Denial_Lines__c", EdgeTypes.READS, "BATCH_SCOPE"))
        edges_set.add(("apex.class.YesterdayDenialSyncBatch", "salesforce.object.Encounter__c", EdgeTypes.WRITES, "ORPHAN_LINKING"))
        edges_set.add(("apex.class.UpdateEncounterOwnerAndRoutingBatch", "salesforce.object.Encounter__c", EdgeTypes.WRITES, "OWNER_ROUTING"))

        edges: List[Edge] = [
            Edge(source_id=s, target_id=t, relationship=r, properties={"type": p})
            for (s, t, r, p) in edges_set
        ]

        return list(nodes_map.values()), edges
