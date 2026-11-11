"""Unit and integration tests for Salesforce Jarvis Voice Engine & Executive Briefing (Milestone 4 Upgrade).

Tests:
1. Executive Briefing high-fidelity British Butler phrasing matching the exact specification:
   "Good morning, sir. Checking Alliance Prod now. All three primary batches completed on schedule.
   CronTrigger monitors confirm zero missed runs. Snowflake daily row-count reconciliation is 100%
   aligned with zero dropped records. SetupAuditTrail reports no unapproved config changes in Production.
   All security certificates nominal, and org-wide code coverage is healthy at 82%. What would you like to inspect first, sir?"
2. Overnight batch health + instant BatchApexErrorEvent alerts (chunk failure with stack trace).
3. CronTrigger scheduler health: confirm all overnight scheduled jobs ran on time and state NextFireTime.
4. SetupAuditTrail: report unapproved config changes directly in Prod yesterday.
5. Integration Attribution: Bulk API 2.0 load volumes and SF <-> Snowflake row-count reconciliation.
6. Certificate & Token Expiry: warn if any certificate or OAuth token is within 14 days of expiration (TeamHotfix/TeamMD/Alliance).
7. Org Limits & Coverage: org-wide code coverage % and API headroom.
8. Verbal voice commands for all new modules.
9. VoiceEngine run_morning_briefing & EventBus trigger.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from app.briefing import (
    ExecutiveBriefing,
    evaluate_batch_health,
    evaluate_certificate_and_token_expiry,
    evaluate_coverage_and_limits,
    evaluate_cron_triggers,
    evaluate_integration_attribution,
    evaluate_setup_audit_trail,
    generate_briefing_text,
    generate_executive_briefing_text,
    get_default_state,
    handle_batch_health_command,
    handle_briefing_command,
    handle_certificate_expiry_command,
    handle_coverage_limits_command,
    handle_integration_command,
    handle_scheduled_jobs_command,
    handle_setup_audit_command,
    load_state,
    run_executive_briefing,
)
from app.event_bus import EventBus
from app.models import EventTopic, VoiceMessage
from app.voice import VoiceEngine, process_verbal_command


class TestExecutiveBriefingMilestone4Upgrade(unittest.TestCase):
    """Test upgraded British Butler Executive Morning Briefing phrasing & signals."""

    def setUp(self):
        self.nominal_state = get_default_state()

    def test_executive_briefing_exact_benchmark_phrasing(self):
        """Verify the exact British Butler benchmark phrasing on nominal telemetry."""
        briefing = generate_executive_briefing_text(self.nominal_state)

        expected_benchmark = (
            "Good morning, sir. Checking Alliance Prod now. "
            "All three primary batches completed on schedule. "
            "CronTrigger monitors confirm zero missed runs. "
            "Snowflake daily row-count reconciliation is 100% aligned with zero dropped records. "
            "SetupAuditTrail reports no unapproved config changes in Production. "
            "All security certificates nominal, and org-wide code coverage is healthy at 82%. "
            "What would you like to inspect first, sir?"
        )
        self.assertEqual(briefing.strip(), expected_benchmark.strip())

    def test_batch_health_instant_batch_apex_error_event(self):
        """Instant alert if any batch chunk failed with stack trace."""
        state = copy.deepcopy(self.nominal_state)
        state["batch_apex_errors"] = [
            {
                "apex_class": "YesterdayDenialSyncBatch",
                "phase": "execute",
                "exception_type": "System.DmlException",
                "message": "FIELD_CUSTOM_VALIDATION_EXCEPTION: Encounter locked during sync",
                "stack_trace": "Class.YesterdayDenialSyncBatch.execute: line 142, column 1",
            }
        ]

        eval_result = evaluate_batch_health(state)
        self.assertFalse(eval_result["is_clean"])
        self.assertEqual(eval_result["status"], "alert")
        self.assertIn("Alert: BatchApexErrorEvent detected chunk failure on YesterdayDenialSyncBatch", eval_result["summary_text"])
        self.assertIn("Class.YesterdayDenialSyncBatch.execute: line 142", eval_result["summary_text"])

        # Check full executive briefing incorporates this alert
        briefing = generate_executive_briefing_text(state)
        self.assertIn("Alert: BatchApexErrorEvent detected chunk failure on YesterdayDenialSyncBatch", briefing)
        self.assertNotIn("All three primary batches completed on schedule.", briefing)

    def test_batch_health_job_error_warning(self):
        """Warning if a batch job completed with errors but no event."""
        state = copy.deepcopy(self.nominal_state)
        state["batches"]["UpdateEncounterOwnerAndRoutingBatch"]["errors"] = 5
        state["batches"]["UpdateEncounterOwnerAndRoutingBatch"]["extended_status"] = "First error: Record locked"

        eval_result = evaluate_batch_health(state)
        self.assertFalse(eval_result["is_clean"])
        self.assertEqual(eval_result["status"], "warning")
        self.assertIn("UpdateEncounterOwnerAndRoutingBatch reported 5 errors", eval_result["summary_text"])

    def test_cron_trigger_scheduler_health_nominal(self):
        """Confirm all overnight scheduled jobs ran on time and zero missed runs."""
        eval_result = evaluate_cron_triggers(self.nominal_state)
        self.assertEqual(eval_result["status"], "nominal")
        self.assertEqual(eval_result["missed_runs"], 0)
        self.assertIn("CronTrigger monitors confirm zero missed runs.", eval_result["summary_text"])
        self.assertIn("Next fire time is 02:00 AM", eval_result["detailed_text"])

    def test_cron_trigger_scheduler_health_missed_runs(self):
        """Warning if CronTrigger detects missed runs."""
        state = copy.deepcopy(self.nominal_state)
        state["cron_triggers"]["missed_runs"] = 2
        state["cron_triggers"]["jobs"][0]["status"] = "ERROR"

        eval_result = evaluate_cron_triggers(state)
        self.assertEqual(eval_result["status"], "warning")
        self.assertEqual(eval_result["missed_runs"], 2)
        self.assertIn("Warning: CronTrigger monitors detected 2 missed runs.", eval_result["summary_text"])

        briefing = generate_executive_briefing_text(state)
        self.assertIn("Warning: CronTrigger monitors detected 2 missed runs.", briefing)

    def test_setup_audit_trail_clean(self):
        """Confirm no unapproved config changes in Production."""
        eval_result = evaluate_setup_audit_trail(self.nominal_state)
        self.assertEqual(eval_result["status"], "nominal")
        self.assertEqual(eval_result["unapproved_count"], 0)
        self.assertIn("SetupAuditTrail reports no unapproved config changes in Production.", eval_result["summary_text"])

    def test_setup_audit_trail_unapproved_prod_changes(self):
        """Warning when critical config changes were made directly in Prod yesterday."""
        state = copy.deepcopy(self.nominal_state)
        state["setup_audit_trail"] = {
            "unapproved_prod_changes": 1,
            "critical_changes_count": 1,
            "is_clean": False,
            "changes": [
                {
                    "action": "changed",
                    "section": "Validation Rules",
                    "display": "Modified VR_Encounter_Lock on Encounter__c",
                    "created_by": "admin@alliancehealth.org",
                    "created_date": "yesterday",
                }
            ],
        }

        eval_result = evaluate_setup_audit_trail(state)
        self.assertEqual(eval_result["status"], "warning")
        self.assertEqual(eval_result["unapproved_count"], 1)
        self.assertIn("SetupAuditTrail detected 1 direct configuration change in Production yesterday", eval_result["summary_text"])
        self.assertIn("VR_Encounter_Lock", eval_result["summary_text"])

        briefing = generate_executive_briefing_text(state)
        self.assertIn("SetupAuditTrail detected 1 direct configuration change in Production yesterday", briefing)

    def test_integration_attribution_nominal(self):
        """Confirm 100% SF <-> Snowflake row-count reconciliation and Bulk API 2.0 volumes."""
        eval_result = evaluate_integration_attribution(self.nominal_state)
        self.assertEqual(eval_result["status"], "nominal")
        self.assertEqual(eval_result["dropped_records"], 0)
        self.assertEqual(eval_result["reconciliation_pct"], 100.0)
        self.assertIn("Snowflake daily row-count reconciliation is 100% aligned with zero dropped records.", eval_result["summary_text"])
        self.assertIn("Bulk API 2.0 processed 150,000 records across 4 load jobs", eval_result["detailed_text"])

    def test_integration_attribution_dropped_records(self):
        """Warning when Snowflake reconciliation drops records."""
        state = copy.deepcopy(self.nominal_state)
        state["integration"]["snowflake_dropped_records"] = 450
        state["integration"]["snowflake_reconciliation_pct"] = 97.2

        eval_result = evaluate_integration_attribution(state)
        self.assertEqual(eval_result["status"], "warning")
        self.assertEqual(eval_result["dropped_records"], 450)
        self.assertIn("Snowflake daily row-count reconciliation detected 450 dropped records with 97.2% alignment.", eval_result["summary_text"])

        briefing = generate_executive_briefing_text(state)
        self.assertIn("Snowflake daily row-count reconciliation detected 450 dropped records", briefing)

    def test_certificate_and_token_expiry_nominal_prod(self):
        """Alliance Prod certificate is nominal, TeamHotfix refresh token status handled."""
        eval_result = evaluate_certificate_and_token_expiry(self.nominal_state)
        self.assertIn("All security certificates nominal", eval_result["summary_text"])
        self.assertIn("TeamHotfix OAuth refresh token is expired", eval_result["detailed_text"])

    def test_certificate_expiry_warning_under_14_days(self):
        """Warn if certificate is within 14 days of expiration."""
        state = copy.deepcopy(self.nominal_state)
        state["certificates"] = [
            {
                "name": "Alliance_SSO_Cert",
                "org": "Alliance Prod",
                "days_until_expiration": 9,
                "status": "EXPIRING_SOON",
            }
        ]

        eval_result = evaluate_certificate_and_token_expiry(state)
        self.assertEqual(eval_result["status"], "warning")
        self.assertIn("Alliance_SSO_Cert for Alliance Prod expires in 9 days", eval_result["summary_text"])

    def test_code_coverage_and_headroom_healthy(self):
        """State org-wide code coverage % and API headroom."""
        eval_result = evaluate_coverage_and_limits(self.nominal_state)
        self.assertEqual(eval_result["status"], "nominal")
        self.assertEqual(eval_result["coverage_pct"], 82.0)
        self.assertIn("and org-wide code coverage is healthy at 82%.", eval_result["summary_text"])
        self.assertIn("API headroom remaining", eval_result["detailed_text"])

    def test_code_coverage_deficient(self):
        """Warning when code coverage drops below 75%."""
        state = copy.deepcopy(self.nominal_state)
        state["code_coverage"]["org_wide_coverage_pct"] = 68.0

        eval_result = evaluate_coverage_and_limits(state)
        self.assertEqual(eval_result["status"], "warning")
        self.assertIn("org-wide code coverage is deficient at 68%", eval_result["summary_text"])

        briefing = generate_executive_briefing_text(state)
        self.assertIn("code coverage is deficient at 68%", briefing)


class TestVerbalCommandsMilestone4Upgrade(unittest.TestCase):
    """Test verbal voice command recognition and responses for new modules."""

    def setUp(self):
        self.mock_engine = MagicMock(spec=VoiceEngine)
        self.state = get_default_state()

    def test_command_check_scheduled_jobs(self):
        handled, msg = process_verbal_command("Jarvis, check scheduled jobs", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertIn("CronTrigger monitors confirm zero missed runs", msg)
        self.assertIn("Next fire time is 02:00 AM", msg)
        self.mock_engine.speak.assert_called_once()

    def test_command_check_cron_triggers(self):
        handled, msg = process_verbal_command("check cron triggers now", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertIn("CronTrigger monitors confirm zero missed runs", msg)

    def test_command_check_certificate_expiry(self):
        handled, msg = process_verbal_command("Jarvis, check certificate expiry", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertIn("Alliance Prod certificate is nominal", msg)
        self.assertIn("TeamHotfix OAuth refresh token is expired", msg)
        self.mock_engine.speak.assert_called_once()

    def test_command_check_setup_audit(self):
        handled, msg = process_verbal_command("Jarvis, check setup audit", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertIn("SetupAuditTrail reports no unapproved configuration changes in Production yesterday", msg)
        self.mock_engine.speak.assert_called_once()

    def test_command_check_snowflake_reconciliation(self):
        handled, msg = process_verbal_command("Jarvis, check snowflake reconciliation", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertIn("Bulk API 2.0 processed 150,000 records across 4 load jobs", msg)
        self.assertIn("100% aligned with zero dropped records", msg)
        self.mock_engine.speak.assert_called_once()

    def test_command_check_integration(self):
        handled, msg = process_verbal_command("Jarvis, check integration status", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertIn("Snowflake daily row-count reconciliation is 100% aligned", msg)

    def test_command_check_code_coverage(self):
        handled, msg = process_verbal_command("Jarvis, check code coverage", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertIn("Org-wide code coverage is healthy at 82%", msg)
        self.assertIn("API headroom remaining", msg)
        self.mock_engine.speak.assert_called_once()

    def test_command_check_batches(self):
        handled, msg = process_verbal_command("Jarvis, check batches", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertIn("All three primary batches completed on schedule with zero errors", msg)
        self.mock_engine.speak.assert_called_once()

    def test_command_run_morning_briefing(self):
        handled, msg = process_verbal_command("Jarvis, run the morning briefing", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertIn("Briefing triggered", msg)
        self.assertIn("Good morning, sir. Checking Alliance Prod now.", msg)
        self.mock_engine.speak.assert_called_once()

    def test_command_mute_and_unmute(self):
        handled, msg = process_verbal_command("Jarvis, please mute", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertEqual(msg, "Voice muted")
        self.mock_engine.mute.assert_called_with(True)

        handled, msg = process_verbal_command("Jarvis, unmute", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertEqual(msg, "Voice unmuted")
        self.mock_engine.unmute.assert_called_once()

    def test_command_stop(self):
        handled, msg = process_verbal_command("Jarvis, stop", self.mock_engine, state=self.state)
        self.assertTrue(handled)
        self.assertEqual(msg, "Speech interrupted")
        self.mock_engine.interrupt.assert_called_once()

    def test_unrecognized_command(self):
        handled, msg = process_verbal_command("what is the weather today", self.mock_engine, state=self.state)
        self.assertFalse(handled)
        self.assertIn("Unrecognized verbal command", msg)


class TestVoiceEngineBriefingIntegration(unittest.TestCase):
    """Test VoiceEngine run_morning_briefing method and EventBus integration."""

    def setUp(self):
        self.engine = VoiceEngine()

    def tearDown(self):
        self.engine.stop()

    def test_run_morning_briefing_method(self):
        """Test VoiceEngine.run_morning_briefing execution."""
        state = get_default_state()
        briefing_text = self.engine.run_morning_briefing(state=state)
        self.assertTrue(len(briefing_text) > 50)
        self.assertIn("Good morning, sir. Checking Alliance Prod now.", briefing_text)

    def test_event_bus_trigger_briefing(self):
        """Test EventTopic.TRIGGER_BRIEFING generates briefing via EventBus."""
        bus = EventBus()
        self.engine.subscribe_to_event_bus(bus)

        # Trigger briefing via EventBus
        bus.publish(EventTopic.TRIGGER_BRIEFING, None)
        # Should enqueue briefing message
        self.assertFalse(self.engine._queue.empty())


if __name__ == "__main__":
    unittest.main()
