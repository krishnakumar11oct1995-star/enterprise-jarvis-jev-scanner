"""Unit and integration tests for Milestone 3 Upgrade (Desktop HUD Cockpit UI v2).

Tests the upgraded Real-Time Mission Control Flight Deck:
- /api/status: AuthSession active users, storage usage %, Salesforce Trust API pod status
- /api/schedulers: CronTrigger schedule status, next fire times, missed run alerts,
                  and BatchApexErrorEvent stack traces with failing record IDs
- /api/deployments: Tooling API DeployRequest progress and SetupAuditTrail prod ticker
- /api/integrations: Bulk API 2.0 jobs, API attribution by app/user, certificate expiration,
                     and Snowflake reconciliation
- /api/governance: Code coverage %, sandbox staleness, and data quality null-rate probes
- Web Cockpit UI markup and components
"""

import unittest
import os
import sys
from pathlib import Path
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ui.server import create_app


class TestDesktopHUDv2(unittest.TestCase):
    """Test suite for HUD v2 Mission Control Flight Deck."""

    def setUp(self):
        self.mock_actions = []

        def mock_window_mgr(action: str):
            self.mock_actions.append(action)
            return f"handled_{action}"

        self.app = create_app(window_manager_callback=mock_window_mgr)
        self.client = TestClient(self.app)

    def test_api_status_extended(self):
        """Validates /api/status contains AuthSession users, storage %, Trust pod status, and governor gauges."""
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Check Active AuthSession users
        self.assertIn("active_users", data)
        active_users = data["active_users"]
        self.assertGreaterEqual(active_users["count"], 1)
        self.assertIn("ui_sessions", active_users)
        self.assertIn("api_sessions", active_users)
        self.assertIsInstance(active_users["users"], list)
        self.assertGreaterEqual(len(active_users["users"]), 1)
        usernames = [u["username"] for u in active_users["users"]]
        self.assertTrue(any("alliance.com" in u or "aptimized.com" in u for u in usernames))

        # Check Storage Usage %
        self.assertIn("storage_usage", data)
        storage = data["storage_usage"]
        self.assertIn("data_storage", storage)
        self.assertIn("file_storage", storage)
        self.assertGreater(storage["data_storage"]["percent"], 0)
        self.assertIn("GB", storage["data_storage"]["used_formatted"])
        self.assertIn("GB", storage["file_storage"]["max_formatted"])

        # Check Trust API Pod status
        self.assertIn("trust_pod", data)
        pod = data["trust_pod"]
        self.assertEqual(pod["instance_pod"], "NA214")
        self.assertEqual(pod["status"], "AVAILABLE")
        self.assertIn("latency_ms", pod)

        # Check Governor Gauges
        self.assertIn("governor_gauges", data)
        gauges = data["governor_gauges"]
        self.assertIn("daily_api_used", gauges)
        self.assertIn("daily_api_max", gauges)
        self.assertEqual(gauges["single_email_used"], 482)
        self.assertEqual(gauges["single_email_max"], 5000)

    def test_api_schedulers(self):
        """Validates /api/schedulers returns CronTriggers and BatchApexErrorEvents with failing record IDs."""
        res = self.client.get("/api/schedulers")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Check Schedulers list
        self.assertIn("schedulers", data)
        schedulers = data["schedulers"]
        self.assertGreaterEqual(len(schedulers), 5)
        names = [s["job_name"] for s in schedulers]
        self.assertIn("NightlyDenialIngestScheduler", names)
        self.assertIn("HourlyCareCloudReconciler", names)
        self.assertIn("LateChargeReconciliationJob", names)

        # Verify next fire times and countdowns
        for s in schedulers:
            self.assertIn("cron_expression", s)
            self.assertIn("next_fire_time", s)
            self.assertIn("status_badge", s)

        # Check missed alert badge
        missed = [s for s in schedulers if s["missed_alert"]]
        self.assertGreaterEqual(len(missed), 1)
        self.assertEqual(missed[0]["status_badge"], "MISSED")

        # Check BatchApexErrorEvent telemetry
        self.assertIn("batch_apex_errors", data)
        errors = data["batch_apex_errors"]
        self.assertGreaterEqual(len(errors), 1)
        err = errors[0]
        self.assertEqual(err["job_name"], "ClaimBillingSyncBatch")
        self.assertEqual(err["exception_type"], "System.DmlException")
        self.assertIn("UNABLE_TO_LOCK_ROW", err["message"])
        self.assertIn("stack_trace", err)
        self.assertIn("failing_record_ids", err)
        self.assertIsInstance(err["failing_record_ids"], list)
        self.assertIn("001UP000003kUp1YAE", err["failing_record_ids"])

    def test_api_deployments(self):
        """Validates /api/deployments returns Tooling API DeployRequest progress and SetupAuditTrail prod ticker."""
        res = self.client.get("/api/deployments")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Check Active DeployRequest
        self.assertIn("active_deployment", data)
        dep = data["active_deployment"]
        self.assertEqual(dep["status"], "InProgress")
        self.assertEqual(dep["components_total"], 18)
        self.assertGreaterEqual(dep["components_deployed"], 10)
        self.assertIn("FlowsheetReconciliationService.cls", dep["current_component"])
        self.assertIn("components_summary", dep)
        self.assertGreaterEqual(len(dep["components_summary"]), 5)

        # Check SetupAuditTrail prod modifications
        self.assertIn("setup_audit_trail", data)
        sat = data["setup_audit_trail"]
        self.assertIn("items", sat)
        self.assertGreaterEqual(len(sat["items"]), 3)
        self.assertGreaterEqual(sat["direct_prod_edits_count"], 1)

        direct_edits = [i for i in sat["items"] if i.get("outside_pipeline")]
        self.assertGreaterEqual(len(direct_edits), 1)
        self.assertIn("Modified FlowsheetValidationTrigger directly in Setup", [i["display"] for i in direct_edits])

    def test_api_integrations(self):
        """Validates /api/integrations returns Bulk API 2.0, API attribution, cert tracker, and Snowflake reconciliation."""
        res = self.client.get("/api/integrations")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Bulk API 2.0 jobs
        self.assertIn("bulk_api_jobs", data)
        bulk_jobs = data["bulk_api_jobs"]
        self.assertGreaterEqual(len(bulk_jobs), 2)
        obj_names = [j["object"] for j in bulk_jobs]
        self.assertIn("Encounter__c", obj_names)
        self.assertIn("Claim__c", obj_names)

        # API attribution by app / user
        self.assertIn("api_attribution", data)
        attr = data["api_attribution"]
        self.assertIn("by_connected_app", attr)
        apps = [a["app"] for a in attr["by_connected_app"]]
        self.assertIn("MuleSoft Enterprise Gateway", apps)
        self.assertIn("CareCloud EHR Ingest", apps)
        self.assertIn("Snowflake DW Loader", apps)
        self.assertIn("by_user", attr)
        self.assertEqual(attr["single_email_meter"]["used"], 482)
        self.assertEqual(attr["single_email_meter"]["limit"], 5000)

        # Certificate expiration tracker & OAuth token countdown
        self.assertIn("certificate_tracker", data)
        certs = data["certificate_tracker"]
        self.assertEqual(len(certs), 3)
        org_names = [c["org"] for c in certs]
        self.assertIn("Alliance Prod", org_names)
        self.assertIn("TeamMD", org_names)
        self.assertIn("TeamHotfix", org_names)
        team_md_cert = next(c for c in certs if c["org"] == "TeamMD")
        self.assertEqual(team_md_cert["expires_in_days"], 12)
        self.assertEqual(team_md_cert["status"], "EXPIRING_SOON")

        # Snowflake DW reconciliation
        self.assertIn("snowflake_reconciliation", data)
        sf_recon = data["snowflake_reconciliation"]
        self.assertEqual(sf_recon["overall_status"], "SYNCED")
        tables = sf_recon["tables"]
        table_names = [t["table"] for t in tables]
        self.assertIn("Encounter__c", table_names)
        self.assertIn("Claim__c", table_names)
        enc_tab = next(t for t in tables if t["table"] == "Encounter__c")
        self.assertEqual(enc_tab["delta"], 2)
        self.assertIn("42s", enc_tab["systemmodstamp_lag"])

    def test_api_governance(self):
        """Validates /api/governance returns code coverage %, sandbox staleness, and data quality null probes."""
        res = self.client.get("/api/governance")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Code coverage %
        self.assertIn("code_coverage", data)
        cov = data["code_coverage"]
        self.assertEqual(cov["overall_coverage_pct"], 78.4)
        self.assertEqual(cov["threshold_pct"], 75.0)
        self.assertIn("classes_below_threshold", cov)
        below_names = [c["class_name"] for c in cov["classes_below_threshold"]]
        self.assertIn("FlowsheetBillingService", below_names)
        self.assertIn("EncounterRoutingHandler", below_names)

        # Sandbox staleness
        self.assertIn("sandbox_staleness", data)
        sandboxes = data["sandbox_staleness"]
        self.assertEqual(len(sandboxes), 2)
        hotfix = next(s for s in sandboxes if s["sandbox_name"] == "TeamHotfix")
        self.assertEqual(hotfix["status"], "STALE")
        self.assertEqual(hotfix["days_since_refresh"], 18)

        # Data quality null-rate probes
        self.assertIn("data_quality_null_probes", data)
        probes = data["data_quality_null_probes"]
        self.assertGreaterEqual(len(probes), 3)
        fields = [f"{p['object']}.{p['field']}" for p in probes]
        self.assertIn("Encounter__c.Discipline__c", fields)
        self.assertIn("Claim__c.Billing_Taxonomy_Code__c", fields)
        self.assertIn("Patient__c.National_Provider_Identifier__c", fields)

    def test_web_cockpit_v2_markup(self):
        """Validates index.html contains all Mission Control Flight Deck elements."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # 1. Mission Control Flight Gauges Bar
        self.assertIn("flight-gauges-bar", html)
        self.assertIn("DATA STORAGE", html)
        self.assertIn("FILE STORAGE", html)
        self.assertIn("DAILY API GAS TANK", html)
        self.assertIn("OUTBOUND SINGLE EMAIL", html)
        self.assertIn("CODE COVERAGE", html)
        self.assertIn("ACTIVE AUTHSESSIONS", html)

        # 2. Cockpit Navigation Tabs
        self.assertIn("cockpit-nav-bar", html)
        self.assertIn("MISSION FLIGHT DECK", html)
        self.assertIn("SCHEDULERS & BATCH TRACE", html)
        self.assertIn("DEPLOYMENTS & PROD AUDIT", html)
        self.assertIn("INTEGRATIONS & GOVERNANCE", html)
        self.assertIn("QUICK TRIAGE & RADAR", html)

        # 3. Real-Time Schedulers & Batches Tab/Widget
        self.assertIn("schedulers-table", html)
        self.assertIn("batch-error-viewer", html)
        self.assertIn("BATCHAPEXERROREVENT INSTANT STACK TRACE", html)

        # 4. Live Deployments & Prod Changes Panel
        self.assertIn("TOOLING API DEPLOYREQUEST", html)
        self.assertIn("deploy-progress-box", html)
        self.assertIn("SETUPAUDITTRAIL TICKER", html)
        self.assertIn("setup-audit-ticker", html)

        # 5. Integrations & Governance Dashboard
        self.assertIn("integrations-dashboard", html)
        self.assertIn("BULK API 2.0 INGEST & QUERY JOBS", html)
        self.assertIn("API CALL ATTRIBUTION BY CONNECTED APP & USER", html)
        self.assertIn("CERTIFICATE & OAUTH EXPIRATION TRACKER", html)
        self.assertIn("SALESFORCE ↔ SNOWFLAKE DW RECONCILIATION", html)
        self.assertIn("governance-dashboard", html)

        # 6. Preserved Elements: Arc Reactor, Triage Dropzone, Memory Search
        self.assertIn("arc-reactor-canvas", html)
        self.assertIn("code-dropzone-box", html)
        self.assertIn("SCAN WITH JEV RADAR", html)
        self.assertIn("memory-search-input", html)
        self.assertIn("briefing-modal-overlay", html)


if __name__ == "__main__":
    unittest.main()

