"""Comprehensive test suite for Salesforce Live Telemetry & Poller Daemon (Milestone 2)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from app.event_bus import EventBus
from app.models import EventTopic, PollerState, Severity
from app.sf_poller import (
    CREATE_NO_WINDOW,
    SalesforceCLI,
    SalesforcePoller,
    extract_json_from_cli_output,
    format_currency_usd,
    format_iso_timestamp,
)


class TestSalesforceCLI(unittest.TestCase):
    """Tests for Salesforce CLI execution utilities and JSON extraction."""

    def test_cli_installed_detection(self) -> None:
        """Verify CLI detection returns a boolean."""
        installed = SalesforceCLI.is_cli_installed()
        self.assertIsInstance(installed, bool)

    def test_extract_json_from_clean_output(self) -> None:
        """Verify extraction from standard clean JSON."""
        raw = '{"status": 0, "result": {"totalSize": 42}}'
        data = extract_json_from_cli_output(raw)
        self.assertIsNotNone(data)
        self.assertEqual(data["result"]["totalSize"], 42)

    def test_extract_json_with_warning_banners(self) -> None:
        """Verify extraction when CLI outputs npm/update warnings before JSON."""
        raw = (
            " »   Warning: @salesforce/cli update available from 2.144.6 to 2.151.7.\n"
            " »   Run npm install -g @salesforce/cli to update.\n"
            '{\n  "status": 0,\n  "result": {\n    "records": [{"Id": "001TEST"}]\n  }\n}'
        )
        data = extract_json_from_cli_output(raw)
        self.assertIsNotNone(data)
        self.assertEqual(data["result"]["records"][0]["Id"], "001TEST")

    def test_extract_json_invalid(self) -> None:
        """Verify invalid or non-JSON output returns None gracefully."""
        self.assertIsNone(extract_json_from_cli_output("Fatal error: command not found"))
        self.assertIsNone(extract_json_from_cli_output(""))
        self.assertIsNone(extract_json_from_cli_output("   \n\t  "))

    def test_format_currency_usd(self) -> None:
        """Verify currency formatter handles various numeric inputs."""
        self.assertEqual(format_currency_usd(0), "$0")
        self.assertEqual(format_currency_usd(None), "$0")
        self.assertEqual(format_currency_usd(1500), "$1,500")
        self.assertEqual(format_currency_usd(4120500), "$4,120,500")
        self.assertEqual(format_currency_usd(23938325.04), "$23,938,325.04")

    @unittest.skipUnless(sys.platform == "win32", "Windows specific stealth flag test")
    def test_create_no_window_constant(self) -> None:
        """Verify Windows CREATE_NO_WINDOW constant is set to 0x08000000."""
        self.assertEqual(CREATE_NO_WINDOW, 0x08000000)


class TestSalesforcePoller(unittest.TestCase):
    """Unit tests for SalesforcePoller logic, fallback generation, and persistence."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "state.json"
        self.cache_file = Path(self.temp_dir.name) / "telemetry_cache.json"
        self.event_bus = EventBus()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_initialization(self) -> None:
        """Verify default configuration and target orgs."""
        poller = SalesforcePoller(
            interval_seconds=60,
            state_file=self.state_file,
            cache_file=self.cache_file,
            mock_mode=True,
            event_bus=self.event_bus,
        )
        self.assertEqual(poller.interval_seconds, 60)
        self.assertIn("Alliance Prod", poller.target_orgs)
        self.assertIn("TeamMD", poller.target_orgs)
        self.assertIn("TeamHotfix", poller.target_orgs)
        self.assertTrue(poller.mock_mode)

    def test_mock_fallback_snapshot_schema(self) -> None:
        """Verify fallback snapshot contains all keys required by voice.py and CONTRACTS.md."""
        poller = SalesforcePoller(
            state_file=self.state_file,
            cache_file=self.cache_file,
            mock_mode=True,
        )
        snapshot = poller.poll_now(force_refresh=True)

        # CONTRACTS.md contracts
        self.assertIn("timestamp", snapshot)
        self.assertIn("formatted_time", snapshot)
        self.assertIn("orgs", snapshot)
        self.assertIn("batches", snapshot)
        self.assertIn("batch_list", snapshot)
        self.assertIn("metrics", snapshot)
        self.assertIn("system_state", snapshot)

        # voice.py and ExecutiveBriefing contracts
        self.assertIn("org_name", snapshot)
        self.assertIn("username", snapshot)
        self.assertIn("connected", snapshot)
        self.assertIn("revenue", snapshot)
        self.assertIn("radar_summary", snapshot)
        self.assertIn("governor_limits", snapshot)

        # Batches verification
        batches = snapshot["batches"]
        self.assertIn("YesterdayDenialSyncBatch", batches)
        self.assertIn("UpdateEncounterOwnerAndRoutingBatch", batches)
        self.assertIn("EncounterMemberIdBatch", batches)

        # Metrics verification
        metrics = snapshot["metrics"]
        self.assertIn("stranded_encounters", metrics)
        self.assertIn("daily_denials", metrics)
        self.assertIn("yesterday_denial_claim_amount", metrics)
        self.assertIn("today_denial_claim_amount", metrics)

        # Verify state.json was written to disk
        self.assertTrue(self.state_file.exists())
        with open(self.state_file, "r", encoding="utf-8") as f:
            persisted = json.load(f)
        self.assertEqual(persisted["org_name"], snapshot["org_name"])

    def test_event_bus_notifications(self) -> None:
        """Verify poller publishes SCAN_STARTED and SCAN_COMPLETED to the EventBus."""
        started_events = []
        completed_events = []

        self.event_bus.subscribe(EventTopic.SCAN_STARTED, lambda p: started_events.append(p))
        self.event_bus.subscribe(EventTopic.SCAN_COMPLETED, lambda p: completed_events.append(p))

        poller = SalesforcePoller(
            state_file=self.state_file,
            cache_file=self.cache_file,
            mock_mode=True,
            event_bus=self.event_bus,
        )
        poller.poll_now()

        self.assertGreaterEqual(len(started_events), 1)
        self.assertGreaterEqual(len(completed_events), 1)
        self.assertIn("system_state", completed_events[0])

    def test_batch_failure_notification_dispatch(self) -> None:
        """Verify toast notification is dispatched when an AsyncApexJob fails."""
        poller = SalesforcePoller(
            state_file=self.state_file,
            cache_file=self.cache_file,
            mock_mode=True,
        )

        failed_batches = {
            "YesterdayDenialSyncBatch": {
                "name": "YesterdayDenialSyncBatch",
                "status": "Failed",
                "completed_time": "02:00 AM",
                "errors": 5,
                "total_processed": 500,
                "total_batches": 10,
                "failed_batches": 5,
                "extended_status": "System.LimitException: Apex CPU time limit exceeded",
                "id": "707FAIL00000001",
            }
        }

        with patch("app.sf_poller.notify_batch_failure") as mock_notify:
            mock_notify.return_value = True

            # First inspection: should dispatch notification
            has_failure = poller._inspect_and_notify_batch_failures(failed_batches, "Alliance Prod")
            self.assertTrue(has_failure)
            mock_notify.assert_called_once()
            args, kwargs = mock_notify.call_args
            self.assertEqual(kwargs["job_name"], "YesterdayDenialSyncBatch")
            self.assertEqual(kwargs["job_id"], "707FAIL00000001")
            self.assertEqual(kwargs["org_name"], "Alliance Prod")

            # Second inspection with identical job ID: should NOT spam duplicate notification
            mock_notify.reset_mock()
            has_failure_2 = poller._inspect_and_notify_batch_failures(failed_batches, "Alliance Prod")
            self.assertTrue(has_failure_2)
            mock_notify.assert_not_called()

    def test_cache_fallback_resilience(self) -> None:
        """Verify poller seamlessly falls back to cached snapshot when offline."""
        poller = SalesforcePoller(
            state_file=self.state_file,
            cache_file=self.cache_file,
            mock_mode=False,
        )

        # Pre-seed cache file
        mock_cached_snapshot = {
            "org_name": "Alliance Prod",
            "system_state": "NOMINAL",
            "cached": True,
            "metrics": {"stranded_encounters": 0, "daily_denials": 100},
            "batches": {
                "YesterdayDenialSyncBatch": {"status": "Completed", "errors": 0},
            },
        }
        poller._save_cache(mock_cached_snapshot)
        self.assertTrue(self.cache_file.exists())

        # Simulate offline/disconnected state with fallback
        snapshot = poller._generate_fallback_snapshot(reason="Network unreachable")
        self.assertEqual(snapshot["org_name"], "Alliance Prod")
        self.assertEqual(snapshot["metrics"]["daily_denials"], 100)
        self.assertEqual(snapshot["system_state"], "WARNING")

    def test_background_thread_lifecycle(self) -> None:
        """Verify thread starts, responds to triggers, and stops cleanly."""
        poller = SalesforcePoller(
            interval_seconds=10,
            state_file=self.state_file,
            cache_file=self.cache_file,
            mock_mode=True,
            event_bus=self.event_bus,
        )

        self.assertFalse(poller._is_running)
        poller.start()
        self.assertTrue(poller._is_running)
        self.assertIsNotNone(poller._thread)
        self.assertTrue(poller._thread.is_alive())
        self.assertTrue(poller._thread.daemon)

        # Trigger immediate scan
        poller.trigger_scan()
        time.sleep(0.1)

        # Clean shutdown
        poller.stop(timeout=2.0)
        self.assertFalse(poller._is_running)


class TestLiveSalesforceIntegration(unittest.TestCase):
    """Live integration tests running against connected Salesforce orgs if CLI is present."""

    @unittest.skipUnless(SalesforceCLI.is_cli_installed(), "Salesforce CLI required for live test")
    def test_live_cli_execution(self) -> None:
        """Verify real `sf org list` command returns structured output."""
        success, data, err = SalesforceCLI.run_command(["org", "list"], timeout_seconds=30)
        self.assertTrue(success)
        self.assertIsNotNone(data)
        self.assertIn("result", data)


if __name__ == "__main__":
    unittest.main()
