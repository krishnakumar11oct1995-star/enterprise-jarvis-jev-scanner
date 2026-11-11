r"""Memory Bridge for Project Jarvis.

Interfaces with the Antigravity Index database (index.sqlite) and transcript repository
at C:\Users\Krishna\Downloads\Antigravity Index to retrieve historical solutions,
past debugging sessions, and root-cause analyses (RCAs) for conflicting components.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from jarvis.config import DEFAULT_INDEX_DIR, DEFAULT_INDEX_DB
from jarvis.graph.models import Conflict


@dataclass
class HistoricalTurn:
    conv_id: str
    timestamp: str
    user_prompt: str
    solution_summary: str
    files_touched: str
    md_file: str
    transcript_path: str
    rank: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "conv_id": self.conv_id,
            "timestamp": self.timestamp,
            "user_prompt": self.user_prompt,
            "solution_summary": self.solution_summary,
            "files_touched": self.files_touched,
            "md_file": self.md_file,
            "transcript_path": self.transcript_path,
            "rank": self.rank,
        }


class MemoryBridge:
    """Connects to Antigravity Index to search memory and retrieve past RCAs."""

    def __init__(self, index_dir: str = DEFAULT_INDEX_DIR):
        self.index_dir = Path(index_dir)
        self.db_path = self.index_dir / "index.sqlite"
        self.conversations_dir = self.index_dir / "conversations"

    def is_available(self) -> bool:
        return self.db_path.exists()

    def search(self, query: str, limit: int = 5) -> List[HistoricalTurn]:
        """Searches historical conversations using FTS5 with fallback to LIKE substring matching."""
        if not self.is_available():
            return []

        results: List[HistoricalTurn] = []
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Attempt FTS5 query
            clean_q = '"' + query.replace('"', '""') + '"'
            try:
                cursor.execute("""
                    SELECT t.conv_id, t.timestamp, t.user_prompt, t.solution_summary, t.files_touched, t.md_file, f.rank
                    FROM turns_fts f
                    JOIN turns t ON f.rowid = t.id
                    WHERE turns_fts MATCH ?
                    ORDER BY f.rank
                    LIMIT ?
                """, (clean_q, limit))
                rows = cursor.fetchall()
                for r in rows:
                    md_path = str(self.conversations_dir / r[5]) if r[5] else ""
                    results.append(HistoricalTurn(
                        conv_id=r[0],
                        timestamp=r[1],
                        user_prompt=r[2],
                        solution_summary=r[3],
                        files_touched=r[4],
                        md_file=r[5],
                        transcript_path=md_path,
                        rank=r[6] if len(r) > 6 else 0.0,
                    ))
            except Exception:
                pass

            # If FTS returned nothing or failed, execute fallback LIKE query
            if not results:
                like_term = f"%{query}%"
                cursor.execute("""
                    SELECT conv_id, timestamp, user_prompt, solution_summary, files_touched, md_file, 0.0
                    FROM turns
                    WHERE user_prompt LIKE ? OR solution_summary LIKE ? OR files_touched LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                """, (like_term, like_term, like_term, limit))
                rows = cursor.fetchall()
                for r in rows:
                    md_path = str(self.conversations_dir / r[5]) if r[5] else ""
                    results.append(HistoricalTurn(
                        conv_id=r[0],
                        timestamp=r[1],
                        user_prompt=r[2],
                        solution_summary=r[3],
                        files_touched=r[4],
                        md_file=r[5],
                        transcript_path=md_path,
                        rank=0.0,
                    ))

        except Exception:
            pass
        finally:
            if conn:
                conn.close()

        return results

    def get_rca_context(
        self,
        component_name: str,
        rule_id: Optional[str] = None,
        limit: int = 3,
    ) -> List[HistoricalTurn]:
        """
        Retrieves root cause analysis records specifically for a given component name.
        Strips prefixes like apex.class., salesforce.object., etc.
        """
        clean_name = component_name.split(".")[-1]
        search_terms = [clean_name]

        # Add rule keyword context
        rule_keywords = {
            "RULE-REC-001": ["recursion", "loop", "batch"],
            "RULE-RACE-002": ["flow", "trigger", "race"],
            "RULE-GOV-003": ["governor", "soql", "limit", "loop"],
            "RULE-GOV-004": ["callout", "dml", "uncommitted"],
            "RULE-CONTR-005": ["contract", "mule", "snowflake", "field"],
            "RULE-LOCK-008": ["lock", "unable to lock row"],
        }

        hits: List[HistoricalTurn] = []
        if rule_id and rule_id in rule_keywords:
            for kw in rule_keywords[rule_id]:
                compound_q = f"{clean_name} {kw}"
                hits = self.search(compound_q, limit=limit)
                if hits:
                    break

        if not hits:
            hits = self.search(clean_name, limit=limit)

        return hits

    def read_transcript(self, md_file: str, max_chars: int = 3000) -> Optional[str]:
        """Reads markdown transcript content from the conversations directory."""
        if not md_file:
            return None
        file_p = self.conversations_dir / md_file
        if not file_p.exists():
            return None
        try:
            with open(file_p, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[:max_chars]
        except Exception:
            return None

    def enrich_conflicts(self, conflicts: List[Conflict]) -> List[Conflict]:
        """
        Enriches a list of detected conflicts with historical context and RCAs
        from the Antigravity Index database.
        """
        if not self.is_available() or not conflicts:
            return conflicts

        for conf in conflicts:
            # Determine candidate component names
            primary = conf.primary_node_id.split(".")[-1]
            secondary = conf.secondary_node_id.split(".")[-1] if conf.secondary_node_id else ""

            # Try primary first
            turns = self.get_rca_context(primary, rule_id=conf.rule_id, limit=2)
            if not turns and secondary:
                turns = self.get_rca_context(secondary, rule_id=conf.rule_id, limit=2)

            if turns:
                best = turns[0]
                conf.historical_conv_id = best.conv_id
                # Synthesize clean summary
                date_str = best.timestamp[:10] if best.timestamp else "past session"
                sol_snippet = best.solution_summary.strip().replace("\n", " ")
                if len(sol_snippet) > 220:
                    sol_snippet = sol_snippet[:217] + "..."

                summary = (
                    f"Historical RCA Match [Conv {best.conv_id[:8]} | {date_str}]: "
                    f"{sol_snippet} (Reference: conversations/{best.md_file})"
                )
                conf.historical_rca_summary = summary

        return conflicts
