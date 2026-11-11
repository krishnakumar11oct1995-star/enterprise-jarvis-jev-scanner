"""Unit and integration tests for Milestone 3 (Desktop HUD Cockpit UI)."""

import unittest
import os
import sys
from pathlib import Path
from starlette.testclient import TestClient

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ui.server import create_app
from app.ui.hud import DesktopHUD, find_available_port


class TestDesktopHUDServer(unittest.TestCase):
    """Test suite for HUD FastAPI server and endpoints."""

    def setUp(self):
        self.mock_actions = []

        def mock_window_mgr(action: str):
            self.mock_actions.append(action)
            return f"handled_{action}"

        self.app = create_app(window_manager_callback=mock_window_mgr)
        self.client = TestClient(self.app)

    def test_static_index_serving(self):
        """Validates that the web cockpit index.html is served at root /."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("J.A.R.V.I.S.", res.text)
        self.assertIn("arc-reactor-canvas", res.text)
        self.assertIn("LIVE ORG STATUS GRID", res.text)

    def test_api_status_org_grid(self):
        """Validates /api/status returns Alliance Prod, TeamMD, and TeamHotfix."""
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertIn("daemon", data)
        self.assertEqual(data["daemon"]["status"], "ONLINE")
        self.assertEqual(data["daemon"]["hotkey"], "Alt + J")

        self.assertIn("orgs", data)
        orgs = data["orgs"]
        self.assertEqual(len(orgs), 3)

        # Check Alliance Prod
        alliance = next((o for o in orgs if o["id"] == "alliance_prod"), None)
        self.assertIsNotNone(alliance)
        self.assertEqual(alliance["org_id"], "00Df2000001HEGJEA4")
        self.assertEqual(alliance["status"], "ONLINE")

        # Check TeamMD
        team_md = next((o for o in orgs if o["id"] == "team_md"), None)
        self.assertIsNotNone(team_md)
        self.assertEqual(team_md["status"], "WARNING")
        self.assertIn("Appointment__c", team_md.get("alert_message", ""))

        # Check TeamHotfix
        team_hotfix = next((o for o in orgs if o["id"] == "team_hotfix"), None)
        self.assertIsNotNone(team_hotfix)
        self.assertEqual(team_hotfix["status"], "STANDBY")

    def test_api_batches_progress(self):
        """Validates /api/batches returns active batch monitor items."""
        res = self.client.get("/api/batches")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertIn("batches", data)
        batches = data["batches"]
        self.assertGreaterEqual(len(batches), 3)

        batch_names = [b["name"] for b in batches]
        self.assertIn("FlowsheetReconciliationBatch", batch_names)
        self.assertIn("ClaimBillingSyncBatch", batch_names)
        self.assertIn("CareCloudSyncBatch", batch_names)

        # Check error count in ClaimBillingSyncBatch
        claim_batch = next(b for b in batches if b["name"] == "ClaimBillingSyncBatch")
        self.assertEqual(claim_batch["errors"], 2)
        self.assertIn("UNABLE_TO_LOCK_ROW", claim_batch["error_details"])

    def test_api_rcm_telemetry(self):
        """Validates /api/rcm returns Healthcare RCM stats."""
        res = self.client.get("/api/rcm")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertIn("summary", data)
        summary = data["summary"]
        self.assertEqual(summary["denials_volume_formatted"], "$142,500")
        self.assertEqual(summary["unrouted_encounters"], 17)
        self.assertEqual(summary["clean_claim_rate"], "96.4%")

        self.assertIn("priority_denials", data)
        self.assertGreaterEqual(len(data["priority_denials"]), 1)

    def test_api_quick_triage_recursion(self):
        """Validates /api/triage detects recursion and triggers Jev System 1."""
        code_snippet = """
        trigger AccountTrigger on Account (after update) {
            update [SELECT Id FROM Contact WHERE AccountId IN :Trigger.new];
        }
        """
        res = self.client.post("/api/triage", json={"code": code_snippet})
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertIn("jev", data)
        self.assertEqual(data["jev"]["domain"], "SALESFORCE_APEX")
        self.assertIn(data["jev"]["risk_score"], ["HIGH", "CRITICAL"])

        self.assertIn("conflicts", data)
        conflicts = data["conflicts"]
        rec_conflict = next((c for c in conflicts if c["rule_id"] == "RULE-REC-001"), None)
        self.assertIsNotNone(rec_conflict)
        self.assertEqual(rec_conflict["severity"], "CRITICAL")
        self.assertIn("recursion", rec_conflict["description"].lower())

    def test_api_quick_triage_clean_code(self):
        """Validates /api/triage passes clean guarded Apex code."""
        clean_code = """
        public with sharing class SafeService {
            private static Boolean isRunning = false;
            public static void run() {
                if (isRunning) return;
                isRunning = true;
                List<Account> accs = [SELECT Id FROM Account LIMIT 10];
            }
        }
        """
        res = self.client.post("/api/triage", json={"code": clean_code})
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertTrue(data["stats"]["quality_gate_passed"])
        self.assertEqual(data["stats"]["critical"], 0)

    def test_api_quick_triage_empty(self):
        """Validates /api/triage returns 400 on empty code."""
        res = self.client.post("/api/triage", json={"code": "   "})
        self.assertEqual(res.status_code, 400)

    def test_api_memory_search(self):
        """Validates /api/memory/search queries Antigravity Index."""
        res = self.client.get("/api/memory/search?q=Flowsheet&limit=3")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("results", data)
        self.assertIn("query", data)
        self.assertEqual(data["query"], "Flowsheet")

    def test_api_morning_briefing(self):
        """Validates /api/briefing synthesizes executive briefing payload."""
        res = self.client.post("/api/briefing")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertIn("title", data)
        self.assertIn("spoken_script", data)
        self.assertIn("Good morning", data["spoken_script"])
        self.assertIn("sections", data)
        self.assertEqual(len(data["sections"]), 4)
        self.assertIn("action_items", data)
        self.assertGreaterEqual(len(data["action_items"]), 3)

    def test_api_window_control(self):
        """Validates /api/hud/window calls window manager callback."""
        res = self.client.post("/api/hud/window", json={"action": "toggle"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("toggle", self.mock_actions)


class TestDesktopHUDLauncher(unittest.TestCase):
    """Test suite for DesktopHUD manager and port allocation."""

    def test_port_finder(self):
        port = find_available_port(8765)
        self.assertIsInstance(port, int)
        self.assertGreaterEqual(port, 8765)

    def test_hud_instance(self):
        hud = DesktopHUD(port=8765, no_window=True)
        self.assertEqual(hud.title, "JARVIS // ENTERPRISE ARCHITECTURE COCKPIT")
        self.assertTrue(hud.is_visible)

        # Test toggle logic
        hud.toggle_visibility()
        # Toggle alters visibility flag or minimizes
        hud.handle_window_action("minimize")
        self.assertFalse(hud.is_visible)
        hud.handle_window_action("show")
        self.assertTrue(hud.is_visible)


if __name__ == "__main__":
    unittest.main()
