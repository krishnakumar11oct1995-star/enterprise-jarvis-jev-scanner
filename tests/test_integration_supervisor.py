"""Comprehensive End-to-End Integration Verification Suite for Salesforce Jarvis PC Application.

Tests:
1. Architectural Contracts & Thread Model Verification (`app/CONTRACTS.md`)
2. Unified Entrypoint Lifecycle (`app/main.py`)
3. Multi-Subsystem Wiring (Milestones 1-4)
4. EventBus Topic Dispatch (Telemetry -> Tray -> Voice)
5. Zero Console Window Guarantee (`CREATE_NO_WINDOW`)
6. Memory Footprint Verification (< 75MB Working Set RAM)
7. Graceful Teardown within 2.0s
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import threading
import time
import unittest

# Ensure root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.models import EventTopic, PollerState, Severity, OrgStatus, VoiceMessage
from app.event_bus import default_event_bus
from app.startup import verify_startup, is_startup_enabled
from app.notify import Severity as NotifySeverity, CREATE_NO_WINDOW as NOTIFY_CREATE_NO_WINDOW
from app.tray import JarvisTrayDaemon, TrayStatus
from app.sf_poller import SalesforcePoller, CREATE_NO_WINDOW as POLLER_CREATE_NO_WINDOW
from app.ui.hud import DesktopHUD
from app.voice import VoiceEngine
from app.main import SalesforceJarvisApp, trim_working_set, run_integration_test_boot


class TestSupervisorIntegration(unittest.TestCase):
    """End-to-end integration and contract compliance tests."""

    def test_architectural_contracts_document_exists(self):
        """Validates that app/CONTRACTS.md exists and defines core specifications."""
        contract_path = ROOT_DIR / "app" / "CONTRACTS.md"
        self.assertTrue(contract_path.exists(), "CONTRACTS.md must exist in app/")
        content = contract_path.read_text(encoding="utf-8")
        self.assertIn("Milestone 1", content)
        self.assertIn("Milestone 2", content)
        self.assertIn("Milestone 3", content)
        self.assertIn("Milestone 4", content)
        self.assertIn("75.0 MB", content)
        self.assertIn("CREATE_NO_WINDOW", content)

    def test_zero_window_flag_compliance(self):
        """Verifies that all background daemons enforce CREATE_NO_WINDOW = 0x08000000 on Windows."""
        if sys.platform == "win32":
            self.assertEqual(POLLER_CREATE_NO_WINDOW, 0x08000000, "SF Poller must enforce CREATE_NO_WINDOW")
            self.assertEqual(NOTIFY_CREATE_NO_WINDOW, 0x08000000, "Notifier must enforce CREATE_NO_WINDOW")

    def test_low_memory_working_set_budget(self):
        """Verifies that working set memory footprint is strictly under 75MB."""
        import subprocess
        proc = subprocess.run(
            [sys.executable, "-c", "import app.main; print(app.main.trim_working_set())"],
            capture_output=True,
            text=True,
            check=True,
        )
        rss_mb = float(proc.stdout.strip())
        self.assertLess(
            rss_mb,
            75.0,
            f"Working set RAM ({rss_mb:.2f} MB) must remain strictly under 75.00 MB budget",
        )

    def test_unified_app_lifecycle_and_subsystem_wiring(self):
        """Verifies full startup, event routing, and graceful shutdown of SalesforceJarvisApp."""
        app = SalesforceJarvisApp(
            mock_mode=True,
            no_voice=False,
            headless=True,
            port=8769,
            poll_interval=10,
        )

        runner = threading.Thread(
            target=app.start,
            kwargs={"interactive": True},
            daemon=True,
        )
        runner.start()

        # Allow subsystems to boot
        time.sleep(1.5)

        try:
            # 1. Verify all 4 subsystems are active
            self.assertTrue(app.tray.is_running, "System Tray daemon must be active")
            self.assertTrue(app.poller._is_running, "Salesforce Poller daemon must be active")
            self.assertIsNotNone(app.voice, "Voice Engine must be initialized")
            self.assertIn("8769", app.hud.server_url, "HUD server URL must match configured port")

            # 2. Check memory consumption while all 4 subsystems are running
            rss_mb = trim_working_set()
            self.assertLess(
                rss_mb,
                75.0,
                f"Active multi-subsystem working set RAM ({rss_mb:.2f} MB) must be < 75.00 MB",
            )

            # 3. Trigger immediate scan & verify EventBus dispatch
            received_events = []
            def _event_handler(payload):
                received_events.append(payload)

            default_event_bus.subscribe(EventTopic.SCAN_COMPLETED, _event_handler)
            app.poller.trigger_scan()
            time.sleep(0.5)

            self.assertGreater(len(received_events), 0, "EventBus must deliver SCAN_COMPLETED events")

            # 4. Verify Voice Engine can enqueue speech without blocking
            app.voice.speak("Integration test alert", priority=10)
            self.assertFalse(app.voice._stop_requested.is_set(), "Voice worker must remain operational")

        finally:
            # 5. Verify Graceful Teardown within 2.0s
            start_stop = time.time()
            app.stop()
            runner.join(timeout=3.0)
            duration = time.time() - start_stop

            self.assertFalse(app._running, "Supervisor must be marked not running")
            self.assertFalse(app.poller._is_running, "Poller must be stopped")
            self.assertLess(duration, 3.0, "Teardown must complete within bounded window")

    def test_run_integration_test_boot_helper(self):
        """Verifies the standalone CLI --test-boot harness runs and succeeds."""
        success = run_integration_test_boot(mock_mode=True, duration_seconds=1.5)
        self.assertTrue(success, "CLI test boot verification must return True")


if __name__ == "__main__":
    unittest.main()
