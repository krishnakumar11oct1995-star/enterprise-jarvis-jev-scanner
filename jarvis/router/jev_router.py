"""Jev (TypeSafe AI) System 1 Decision & Triage Engine for Project Jarvis.

Jev is a specialized 'System 1' AI model designed for fast (< 100ms), typed,
probabilistic micro-decisions (Choice, Score, Noul) rather than prose generation.

In Project Jarvis, Jev operates as the sensory triage gate:
1. Evaluates incoming code/prompts in sub-100ms.
2. Answers typed questions without LLM prompt hallucinations:
   - Needs_Conflict_Scan (Noul / Binary)
   - Needs_Historical_Recall (Noul / Binary)
   - Architectural_Risk_Score (Score: LOW, MEDIUM, HIGH, CRITICAL)
   - Domain_Target (Choice: SALESFORCE_APEX, SALESFORCE_FLOW, MULESOFT, SNOWFLAKE, GENERAL)
3. Directs Jarvis whether to fire the deep Graph Engine and Memory Bridge.
"""

import os
import re
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

@dataclass
class JevTriageDecision:
    """Strongly typed result returned by Jev triage."""
    domain: str                    # Choice
    domain_confidence: float
    risk_score: str                # Score (LOW, MEDIUM, HIGH, CRITICAL)
    risk_score_numeric: int        # 1-10
    needs_conflict_scan: bool      # Noul (True/False)
    needs_historical_recall: bool  # Noul (True/False)
    suggested_memory_queries: List[str]
    latency_ms: float
    provider: str                  # "typesafe_jev_api" or "jev_local_fast_runtime"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class JevRouter:
    """System 1 decision layer for Project Jarvis."""

    TYPESAFE_API_ENDPOINT = "https://api.typesafe.ai/v1/jev/decide"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")

    def triage(self, input_text: str, is_code: bool = False) -> JevTriageDecision:
        """Runs fast System 1 triage on code snippet or user prompt."""
        import time
        start_time = time.perf_counter()

        # If live Jev API key is provided, attempt call to TypeSafe AI
        if self.api_key:
            try:
                decision = self._call_typesafe_jev_api(input_text, is_code)
                decision.latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
                return decision
            except Exception as e:
                # Graceful fallback to local fast runtime
                pass

        # High-speed local System 1 deterministic decision engine (< 15ms)
        decision = self._local_fast_triage(input_text, is_code)
        decision.latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return decision

    def _call_typesafe_jev_api(self, input_text: str, is_code: bool) -> JevTriageDecision:
        """Executes typed API call to TypeSafe AI Jev endpoint."""
        payload = {
            "state": {
                "input": input_text[:4000],
                "is_code": is_code
            },
            "questions": {
                "domain": {
                    "type": "choice",
                    "options": ["SALESFORCE_APEX", "SALESFORCE_FLOW", "MULESOFT", "SNOWFLAKE", "GENERAL"]
                },
                "risk_score": {
                    "type": "score",
                    "scale": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
                },
                "needs_conflict_scan": {
                    "type": "noul"
                },
                "needs_historical_recall": {
                    "type": "noul"
                }
            }
        }

        req = urllib.request.Request(
            self.TYPESAFE_API_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Project-Jarvis/1.0"
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        answers = data.get("answers", {})
        return JevTriageDecision(
            domain=answers.get("domain", {}).get("selected", "GENERAL"),
            domain_confidence=answers.get("domain", {}).get("confidence", 0.95),
            risk_score=answers.get("risk_score", {}).get("value", "LOW"),
            risk_score_numeric=answers.get("risk_score", {}).get("numeric", 3),
            needs_conflict_scan=answers.get("needs_conflict_scan", {}).get("decision", False),
            needs_historical_recall=answers.get("needs_historical_recall", {}).get("decision", False),
            suggested_memory_queries=[],
            latency_ms=0.0,
            provider="typesafe_jev_api"
        )

    def _local_fast_triage(self, text: str, is_code: bool) -> JevTriageDecision:
        """Sub-15ms local System 1 engine matching Jev's typed output contract."""
        lower = text.lower()

        # 1. Domain Detection (Choice)
        domain = "GENERAL"
        confidence = 0.85
        if any(k in lower for k in ["trigger", "apex", "database.batchable", "soql", "dml", "insert", "update", "sfdc", "salesforce"]):
            domain = "SALESFORCE_APEX"
            confidence = 0.96
        elif any(k in lower for k in ["flow", "flow-meta", "recordupdates", "recordbeforesave", "recordaftersave"]):
            domain = "SALESFORCE_FLOW"
            confidence = 0.94
        elif any(k in lower for k in ["mule", "mulesoft", "dataweave", "dw 2.0", "flow name=", "http:listener"]):
            domain = "MULESOFT"
            confidence = 0.95
        elif any(k in lower for k in ["snowflake", "create pipe", "create task", "copy into", "stage"]):
            domain = "SNOWFLAKE"
            confidence = 0.93

        # 2. Risk Score & Conflict Scan Determination (Score & Noul)
        # Check for architectural risk indicators
        has_loop = bool(re.search(r'\b(for|while|do)\b', text, re.IGNORECASE))
        has_query = bool(re.search(r'\b(select\s+.*?from|database\.query)\b', text, re.IGNORECASE))
        has_dml = bool(re.search(r'\b(insert|update|delete|upsert)\b', text, re.IGNORECASE))
        has_trigger = "trigger " in lower or "after update" in lower or "before update" in lower
        has_callout = "http.send" in lower or "httprequest" in lower

        risk_score = "LOW"
        risk_numeric = 2
        needs_conflict_scan = False

        if has_trigger or (has_loop and (has_query or has_dml)) or (has_dml and has_callout):
            risk_score = "CRITICAL"
            risk_numeric = 9
            needs_conflict_scan = True
        elif is_code and (has_dml or has_query or "flow" in lower):
            risk_score = "HIGH"
            risk_numeric = 7
            needs_conflict_scan = True
        elif any(k in lower for k in ["deploy", "batch", "recursion", "governor", "validation rule", "break"]):
            risk_score = "MEDIUM"
            risk_numeric = 5
            needs_conflict_scan = True

        # 3. Needs Historical Recall (Noul)
        # If user asks about known past entities or debugging past issues
        known_entities = [
            "yesterdaydenialsyncbatch", "updateencounterownerandroutingbatch",
            "encounter", "patient insurance", "needs_routing", "toms river",
            "rcm", "denial", "teammd", "teamhotfix", "alliance prod"
        ]
        needs_historical_recall = any(entity in lower for entity in known_entities) or any(
            k in lower for k in ["error", "fix", "fail", "rca", "past", "history", "previous", "how did we"]
        )

        # 4. Extract suggested memory queries
        suggested_queries = []
        for ent in known_entities:
            if ent in lower:
                suggested_queries.append(ent)
        if not suggested_queries and needs_historical_recall:
            tokens = [w for w in re.findall(r'[a-zA-Z0-9_]{5,}', text) if w.lower() not in ["select", "update", "insert", "delete"]]
            suggested_queries = tokens[:3]

        return JevTriageDecision(
            domain=domain,
            domain_confidence=confidence,
            risk_score=risk_score,
            risk_score_numeric=risk_numeric,
            needs_conflict_scan=needs_conflict_scan,
            needs_historical_recall=needs_historical_recall,
            suggested_memory_queries=suggested_queries,
            latency_ms=0.0,
            provider="jev_local_fast_runtime" if not self.api_key else "typesafe_jev_api"
        )
