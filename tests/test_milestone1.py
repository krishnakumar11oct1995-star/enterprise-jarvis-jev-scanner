"""Comprehensive Test Suite for Milestone 1: Windows Boot Auto-start, Tray Daemon, and Toast Notifications."""

import os
import sys
import time
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.startup import (
    get_startup_dir,
    get_pythonw_executable,
    get_project_root,
    get_vbs_launcher_path,
    generate_vbs_script,
    register_startup,
    unregister_startup,
    is_startup_enabled,
    verify_startup,
    toggle_startup,
    DEFAULT_SHORTCUT_NAME,
    DEFAULT_VBS_NAME,
)

from app.notify import (
    Severity,
    ToastAction,
    ToastNotification,
    build_toast_xml,
    send_toast,
    notify_salesforce_issue,
    notify_batch_failure,
    notify_governor_limit_warning,
    notify_nominal_health,
    get_notification_history,
    clear_notification_history,
)

from app.tray import (
    TrayStatus,
    JarvisTrayDaemon,
    render_status_icon,
)


# =====================================================================
# Startup Tests
# =====================================================================

class TestStartup:
    """Tests for Windows Startup registration, VBS launcher, and verification."""

    def test_paths_resolution(self):
        startup_dir = get_startup_dir()
        assert startup_dir.exists()
        assert "Startup" in str(startup_dir)

        pythonw = get_pythonw_executable()
        assert pythonw.exists()
        assert "pythonw.exe" in pythonw.name.lower() or "python.exe" in pythonw.name.lower()

        root = get_project_root()
        assert root.is_dir()
        assert (root / "app").is_dir()

    def test_vbs_generation_with_spaces_and_quotes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            # Create a path with spaces
            spaced_script = temp_path / "Program Files" / "Jarvis Workspace" / "main app.py"
            spaced_script.parent.mkdir(parents=True, exist_ok=True)
            spaced_script.write_text("print('hello')", encoding="utf-8")

            dest_vbs = temp_path / "launch_test.vbs"
            res = generate_vbs_script(target_script=spaced_script, output_vbs_path=dest_vbs)

            assert res.is_file()
            content = res.read_text(encoding="utf-8")
            assert "WshShell.Run cmd, 0, False" in content
            assert "Chr(34)" in content
            assert str(spaced_script) in content

    def test_shortcut_registration_and_lifecycle(self):
        test_shortcut_name = "Salesforce Jarvis Unit Test.lnk"
        
        # Ensure clean initial state
        unregister_startup(shortcut_name=test_shortcut_name)
        assert not is_startup_enabled(shortcut_name=test_shortcut_name)

        try:
            # Register startup
            reg_result = register_startup(shortcut_name=test_shortcut_name)
            assert reg_result["success"] is True
            assert is_startup_enabled(shortcut_name=test_shortcut_name) is True

            # Verify startup
            v = verify_startup(shortcut_name=test_shortcut_name)
            assert v["enabled"] is True
            assert v["shortcut_exists"] is True
            assert v["vbs_exists"] is True
            assert v["pythonw_exists"] is True
            assert v["valid"] is True
            assert "wscript.exe" in v["shortcut_properties"]["target_path"].lower()

            # Test toggle from enabled -> disabled
            state_after_toggle_1 = toggle_startup(shortcut_name=test_shortcut_name)
            assert state_after_toggle_1 is False
            assert not is_startup_enabled(shortcut_name=test_shortcut_name)

            # Test toggle from disabled -> enabled
            state_after_toggle_2 = toggle_startup(shortcut_name=test_shortcut_name)
            assert state_after_toggle_2 is True
            assert is_startup_enabled(shortcut_name=test_shortcut_name)

        finally:
            # Clean up test shortcut
            unregister_startup(shortcut_name=test_shortcut_name)
            assert not is_startup_enabled(shortcut_name=test_shortcut_name)


# =====================================================================
# Toast Notification Tests
# =====================================================================

class TestNotify:
    """Tests for native Windows Toast Notifications."""

    def setup_method(self):
        clear_notification_history()

    def test_severity_parsing(self):
        assert Severity.from_str("INFO") == Severity.INFO
        assert Severity.from_str("info") == Severity.INFO
        assert Severity.from_str("warning") == Severity.WARNING
        assert Severity.from_str("WARN") == Severity.WARNING
        assert Severity.from_str("error") == Severity.ERROR
        assert Severity.from_str("CRITICAL") == Severity.ERROR
        assert Severity.from_str(Severity.ERROR) == Severity.ERROR

    def test_toast_action_xml(self):
        act = ToastAction(content="Fix Conflict & Open", arguments="https://org.salesforce.com?id=123&action=edit")
        xml_str = act.to_xml()
        assert "Fix Conflict &amp; Open" in xml_str
        assert "https://org.salesforce.com?id=123&amp;action=edit" in xml_str
        assert 'activationType="protocol"' in xml_str

    def test_build_toast_xml_validity(self):
        actions = [
            ToastAction("Open HUD", "https://localhost:8000"),
            ToastAction("View Docs", "https://help.salesforce.com"),
        ]
        xml_str = build_toast_xml(
            title="Apex Conflict <Trigger recursion>",
            message="Circular dependency found between Account & Contact",
            severity=Severity.ERROR,
            actions=actions,
            sound=True,
            attribution="Salesforce Jarvis • Production",
            launch_arg="https://localhost:8000",
        )

        # Validate that the generated XML is strictly valid XML
        root = ET.fromstring(xml_str)
        assert root.tag == "toast"
        assert root.attrib.get("scenario") == "urgent"
        assert root.attrib.get("launch") == "https://localhost:8000"

        # Check visual texts
        texts = root.findall(".//text")
        assert len(texts) == 3
        assert "🔴 Apex Conflict" in texts[0].text
        assert "Circular dependency found" in texts[1].text
        assert "Salesforce Jarvis • Production" in texts[2].text

        # Check action elements
        act_elems = root.findall(".//actions/action")
        assert len(act_elems) == 2
        assert act_elems[0].attrib.get("content") == "Open HUD"

    def test_dry_run_dispatch_and_history(self):
        clear_notification_history()
        ok = send_toast(
            title="Dry Run Test",
            message="This is a test message",
            severity=Severity.WARNING,
            dry_run=True,
        )
        assert ok is True
        hist = get_notification_history()
        assert len(hist) == 1
        assert hist[0].title == "Dry Run Test"
        assert hist[0].severity == Severity.WARNING
        assert hist[0].success is True

    def test_specialized_notification_helpers(self):
        clear_notification_history()
        # Set dry run env var
        os.environ["JARVIS_NOTIFY_DRY_RUN"] = "1"
        try:
            r1 = notify_salesforce_issue("SandBox01", "Recursion loop detected", severity=Severity.ERROR)
            assert r1 is True

            r2 = notify_batch_failure("AccountSyncBatch", "UNABLE_TO_LOCK_ROW", job_id="707XX00001", org_name="Production")
            assert r2 is True

            r3 = notify_governor_limit_warning("ContactTriggerHandler", "SOQL queries", 85.0, 100, org_name="UAT")
            assert r3 is True

            r4 = notify_nominal_health("Production")
            assert r4 is True

            hist = get_notification_history()
            assert len(hist) == 4
            assert "Salesforce Conflict: SandBox01" in hist[0].title
            assert "Apex Batch Failure (Production)" in hist[1].title
            assert "Governor Limit Warning (85%)" in hist[2].title
            assert "System Nominal: Production" in hist[3].title
        finally:
            os.environ.pop("JARVIS_NOTIFY_DRY_RUN", None)

    def test_live_toast_dispatch(self):
        """Dispatches an actual native toast notification with wait=True."""
        ok = send_toast(
            title="Unit Test Toast",
            message="Verifying live Windows WinRT dispatch",
            severity=Severity.INFO,
            sound=False,
            wait=True,
        )
        assert ok is True


# =====================================================================
# System Tray Daemon Tests
# =====================================================================

class TestTray:
    """Tests for dynamic icon rendering and system tray daemon."""

    def test_render_status_icons(self):
        for status in [TrayStatus.NOMINAL, TrayStatus.WARNING, TrayStatus.ERROR]:
            img = render_status_icon(status, size=(64, 64))
            assert img.size == (64, 64)
            assert img.mode == "RGBA"
            # Ensure not all pixels are transparent
            pixels = list(img.getdata())
            visible_pixels = [p for p in pixels if p[3] > 0]
            assert len(visible_pixels) > 100

    def test_tray_daemon_initialization_and_menu(self):
        daemon = JarvisTrayDaemon(initial_status=TrayStatus.NOMINAL)
        assert daemon.status == TrayStatus.NOMINAL
        assert daemon.is_running is False

        # Verify menu items exist
        menu = daemon._icon.menu
        menu_items = list(menu.items)
        assert len(menu_items) >= 5

        # Check first menu item is default and Open Cockpit
        open_cockpit_item = menu_items[0]
        assert "Open Cockpit" in str(open_cockpit_item.text)
        assert open_cockpit_item.default is True

        # Check Exit menu item exists
        exit_item = menu_items[-1]
        assert "Exit" in str(exit_item.text)

    def test_tray_daemon_status_updates(self):
        daemon = JarvisTrayDaemon(initial_status=TrayStatus.NOMINAL)
        assert daemon.status == TrayStatus.NOMINAL

        daemon.set_status(TrayStatus.WARNING, tooltip_suffix="Apex limit warning")
        assert daemon.status == TrayStatus.WARNING
        assert "WARNING" in daemon._icon.title
        assert "Apex limit warning" in daemon._icon.title

        daemon.set_status(TrayStatus.ERROR, tooltip_suffix="1 Batch failed")
        assert daemon.status == TrayStatus.ERROR
        assert "ERROR" in daemon._icon.title

    def test_tray_daemon_callbacks(self):
        cockpit_called = []
        briefing_called = []
        refresh_called = []
        exit_called = []

        daemon = JarvisTrayDaemon(
            on_open_cockpit=lambda: cockpit_called.append(True),
            on_morning_briefing=lambda: briefing_called.append(True),
            on_refresh_status=lambda: refresh_called.append(True),
            on_exit=lambda: exit_called.append(True),
        )

        daemon._action_open_cockpit()
        assert len(cockpit_called) == 1

        daemon._action_morning_briefing()
        assert len(briefing_called) == 1

        daemon._action_refresh_status()
        assert len(refresh_called) == 1

        daemon.stop()
        assert len(exit_called) == 1

    def test_tray_daemon_detached_lifecycle(self):
        daemon = JarvisTrayDaemon(initial_status=TrayStatus.NOMINAL)
        daemon.start(detached=True)
        time.sleep(0.4)
        assert daemon.is_running is True

        daemon.set_status(TrayStatus.WARNING)
        time.sleep(0.2)
        assert daemon.status == TrayStatus.WARNING

        daemon.stop()
        time.sleep(0.4)
        assert daemon.is_running is False
