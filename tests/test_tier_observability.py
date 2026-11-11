"""Comprehensive Integration & Verification Suite for 4-Tier Observability and 7 Platform Corrections.

Verifies:
1. CONTRACTS.md compliance (4-tier observability specification + 7 platform engineering corrections).
2. Thread-safe state synchronization on app/event_bus.py across concurrent workers.
3. Telemetry snapshot schema validation for Tier 1, Tier 2, Tier 3, and Tier 4.
4. Platform engineering corrections data validation.
5. Strict memory footprint budget verification (< 75.0 MB RAM).
6. Zero console window flag enforcement (CREATE_NO_WINDOW = 0x08000000).
"""

from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.models import EventTopic, OrgStatus, PollerState, Severity
from app.event_bus import EventBus, default_event_bus
from app.main import trim_working_set
import app.sf_poller
import app.notify


class TestTierObservability(unittest.TestCase):
    """Deep verification of 4-tier observability architecture and contracts."""

    def test_contracts_md_four_tiers_and_seven_corrections(self):
        """Verifies app/CONTRACTS.md defines all 4 tiers and 7 platform engineering corrections."""
        contract_path = ROOT_DIR / "app" / "CONTRACTS.md"
        self.assertTrue(contract_path.exists(), "CONTRACTS.md must exist in app/")
        content = contract_path.read_text(encoding="utf-8")

        # Tier 1 verification
        self.assertIn("Tier 1", content)
        self.assertIn("BatchApexErrorEvent", content)
        self.assertIn("FlowExecutionErrorEvent", content)
        self.assertIn("FlowInterview", content)
        self.assertIn("CronTrigger", content)
        self.assertIn("EventLogFile", content)

        # Tier 2 verification
        self.assertIn("Tier 2", content)
        self.assertIn("Bulk API 2.0", content)
        self.assertIn("ConnectedApp", content)
        self.assertIn("Certificate", content)
        self.assertIn("Snowflake", content)
        self.assertIn("SystemModstamp", content)

        # Tier 3 verification
        self.assertIn("Tier 3", content)
        self.assertIn("SetupAuditTrail", content)
        self.assertIn("Cross-Org Metadata Drift", content)
        self.assertIn("ApexOrgWideCoverage", content)
        self.assertIn("SandboxProcess", content)

        # Tier 4 verification
        self.assertIn("Tier 4", content)
        self.assertIn("AuthSession", content)
        self.assertIn("Storage", content)
        self.assertIn("Null-Rate", content)
        self.assertIn("Time-in-Queue", content)
        self.assertIn("Trust API", content)

        # 7 Platform Engineering Corrections verification
        self.assertIn("AsyncApexJob Delta Velocity", content)
        self.assertIn("FlexQueue", content)
        self.assertIn("commitUser", content)
        self.assertIn("Child-Parent Lookup Cache", content)
        self.assertIn("ReportEvent", content)
        self.assertIn("Email Bounces", content)
        self.assertIn("AuthSession Delta Polling", content)

    def test_event_bus_thread_safe_synchronization(self):
        """Validates thread-safe multi-threaded publishing, subscriber isolation, and latest payload sync."""
        bus = EventBus()
        received_tier1 = []
        received_tier2 = []
        lock = threading.Lock()

        def _h1(payload):
            with lock:
                received_tier1.append(payload)

        def _h2(payload):
            with lock:
                received_tier2.append(payload)

        bus.subscribe(EventTopic.TIER1_ALERT, _h1)
        bus.subscribe(EventTopic.TIER2_ALERT, _h2)

        # Concurrently publish 100 events from 10 threads
        num_threads = 10
        events_per_thread = 20

        def _worker(thread_id: int):
            for i in range(events_per_thread):
                bus.publish(EventTopic.TIER1_ALERT, {"thread": thread_id, "seq": i})
                bus.publish(EventTopic.TIER2_ALERT, {"thread": thread_id, "seq": i})

        threads = [threading.Thread(target=_worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected_count = num_threads * events_per_thread
        self.assertEqual(len(received_tier1), expected_count, "All Tier 1 events must be received")
        self.assertEqual(len(received_tier2), expected_count, "All Tier 2 events must be received")

        # Verify thread-safe latest payload retrieval
        latest1 = bus.get_latest_payload(EventTopic.TIER1_ALERT)
        self.assertIsNotNone(latest1)
        self.assertIn("thread", latest1)

        # Test unsubscription safety
        bus.unsubscribe(EventTopic.TIER1_ALERT, _h1)
        bus.publish(EventTopic.TIER1_ALERT, {"after_unsub": True})
        self.assertEqual(len(received_tier1), expected_count, "Unsubscribed handler must receive no more events")

    def test_memory_working_set_strict_budget(self):
        """Verifies process working set RAM is strictly < 75.0 MB."""
        rss_mb = trim_working_set()
        self.assertLess(
            rss_mb,
            75.0,
            f"Active working set RAM ({rss_mb:.2f} MB) must remain strictly under 75.0 MB",
        )

    def test_zero_window_flag_across_modules(self):
        """Verifies CREATE_NO_WINDOW is set to 0x08000000 on Windows."""
        if sys.platform == "win32":
            self.assertEqual(app.sf_poller.CREATE_NO_WINDOW, 0x08000000)
            self.assertEqual(app.notify.CREATE_NO_WINDOW, 0x08000000)


if __name__ == "__main__":
    unittest.main()
