"""Unit and integration tests for Salesforce AI Core and Copilot Endpoints."""

import unittest
import os
import sys
from pathlib import Path
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ai_core import SalesforceAICore, IncidentDiagnosis, BatchForecast
from app.ui.server import create_app


class TestSalesforceAICore(unittest.TestCase):
    """Test suite for the multi-model AI reasoning engine."""

    def setUp(self):
        self.ai = SalesforceAICore()

    def test_investigate_incident(self):
        """Verifies autonomous causal root cause analysis and git diff synthesis."""
        incident = {
            "id": "INC-8924",
            "component": "YesterdayDenialSyncBatch",
            "error": "System.LimitException: Apex CPU time limit exceeded",
            "failing_ids": ["001UP000003kUp1YAE", "001UP000003kUp2YAE"],
            "org": "Alliance Prod"
        }
        diagnosis = self.ai.investigate(incident)

        self.assertIsInstance(diagnosis, IncidentDiagnosis)
        self.assertEqual(diagnosis.incident_id, "INC-8924")
        self.assertEqual(diagnosis.component_name, "YesterdayDenialSyncBatch")
        self.assertIn("YesterdayDenialSyncBatch.cls", diagnosis.git_diff)
        self.assertIn("--- a/", diagnosis.git_diff)
        self.assertIn("+++ b/", diagnosis.git_diff)
        self.assertGreater(len(diagnosis.causal_chain), 1)
        self.assertIn("Horizon BCBS", diagnosis.causal_chain[0])
        self.assertIn("Test.startTest()", diagnosis.verification_script)
        self.assertGreaterEqual(diagnosis.confidence_score, 0.90)

    def test_forecast_batch_risk(self):
        """Verifies predictive shadow forecasting under volume surges."""
        # Elevated volume test (1,704 denials)
        forecast = self.ai.forecast_batch_risk({"incoming_denials": 1704})
        self.assertIsInstance(forecast, BatchForecast)
        self.assertEqual(forecast.incoming_record_volume, 1704)
        self.assertEqual(forecast.risk_level, "ELEVATED")
        self.assertEqual(forecast.recommended_chunk_size, 120)
        self.assertGreater(forecast.projected_cpu_time_ms, 7500)

        # Critical volume test (2,500 denials)
        crit_forecast = self.ai.forecast_batch_risk({"incoming_denials": 2500})
        self.assertEqual(crit_forecast.risk_level, "CRITICAL")
        self.assertEqual(crit_forecast.recommended_chunk_size, 75)
        self.assertEqual(crit_forecast.failure_probability_pct, 88)

    def test_copilot_chat_encounter_reassign(self):
        """Verifies copilot synthesizes anonymous Apex with trigger bypass for stranded encounters."""
        resp = self.ai.copilot_chat("Draft script to reassign 18 unrouted encounters for Toms River clinic", {})
        self.assertIn("remediation script", resp["reply"].lower())
        self.assertIsNotNone(resp.get("action_card"))
        action_card = resp["action_card"]
        self.assertEqual(action_card["type"], "ANONYMOUS_APEX")
        self.assertIn("bypassTrigger", action_card["code"])
        self.assertIn("Toms River", action_card["code"])

    def test_copilot_chat_denial_anomaly(self):
        """Verifies copilot detects Horizon BCBS CO-16 correlation with MuleSoft API gateway."""
        resp = self.ai.copilot_chat("Why is there a spike in denials today?", {})
        self.assertIn("Horizon BCBS", resp["reply"])
        self.assertIn("CO-16", resp["reply"])
        self.assertIsNotNone(resp.get("action_card"))
        action_card = resp["action_card"]
        self.assertEqual(action_card["type"], "ANOMALY_CLUSTER")
        self.assertIn("SELECT Clinic__c", action_card["code"])


class TestAIEndpoints(unittest.TestCase):
    """Test suite for AI REST API routes on the HUD server."""

    def setUp(self):
        self.app = create_app()
        self.client = TestClient(self.app)

    def test_api_ai_status(self):
        """Verifies /api/ai/status returns active provider and capabilities."""
        res = self.client.get("/api/ai/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ONLINE")
        self.assertIn("active_provider", data)
        self.assertIn("capabilities", data)
        self.assertGreaterEqual(len(data["capabilities"]), 4)

    def test_api_ai_investigate(self):
        """Verifies /api/ai/investigate endpoint outputs full diagnosis."""
        payload = {
            "incident_id": "INC-8924",
            "component": "YesterdayDenialSyncBatch",
            "error": "System.LimitException: Apex CPU time limit exceeded",
            "org": "Alliance Prod"
        }
        res = self.client.post("/api/ai/investigate", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn("diagnosis", data)
        diag = data["diagnosis"]
        self.assertEqual(diag["component_name"], "YesterdayDenialSyncBatch")
        self.assertIn("YesterdayDenialSyncBatch.cls", diag["git_diff"])

    def test_api_ai_predict(self):
        """Verifies /api/ai/predict forecasts CPU consumption."""
        res = self.client.post("/api/ai/predict", json={"incoming_denials": 1704})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["forecast"]["risk_level"], "ELEVATED")

    def test_api_ai_chat(self):
        """Verifies /api/ai/chat returns contextual replies."""
        res = self.client.post("/api/ai/chat", json={"query": "Draft anonymous apex to reassign unrouted encounters"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn("bypassTrigger", data["action_card"]["code"])

    def test_api_ai_config(self):
        """Verifies runtime API key configuration."""
        res = self.client.post("/api/ai/config", json={"anthropic_key": "sk-ant-test-key-12345"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["has_anthropic_key"])
        self.assertEqual(data["active_provider"], "Anthropic Claude 3.5 Sonnet")

        # Reset key to empty for clean environment
        self.client.post("/api/ai/config", json={"anthropic_key": ""})

    def test_web_cockpit_copilot_markup(self):
        """Verifies index.html serves AI Copilot elements."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn("tab-copilot", html)
        self.assertIn("AUTONOMOUS SRE COPILOT", html)
        self.assertIn("run-ai-investigate-btn", html)
        self.assertIn("CAUSAL ROOT CAUSE ANALYSIS", html)
        self.assertIn("YesterdayDenialSyncBatch.cls", html)
        self.assertIn("PREDICTIVE SHADOW SIMULATOR", html)
        self.assertIn("sim-volume-input", html)
        self.assertIn("ENGINEERING CO-PILOT WORKSPACE", html)
        self.assertIn("copilot-input", html)
        self.assertIn("ai-config-modal-overlay", html)


if __name__ == "__main__":
    unittest.main()
