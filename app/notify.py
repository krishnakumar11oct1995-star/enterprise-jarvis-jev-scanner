"""Native Windows Toast Notification Dispatcher for Salesforce Jarvis.

Provides native Windows Toast Notifications via PowerShell WinRT with
graceful fallbacks. Supports:
- Severity levels: INFO, WARNING, ERROR (with custom sounds, prefixes, and urgent scenarios).
- Interactive Action Buttons (protocol URL activations or custom arguments).
- Thread-safe non-blocking asynchronous dispatch.
- Robust character escaping and UTF-16 Base64 encoding.
- Telemetry history and dry-run testing support.
"""

from __future__ import annotations

import os
import sys
import html
import base64
import logging
import threading
import subprocess
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Union, Dict, Any, Callable

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class Severity(str, Enum):
    """Notification severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"

    @classmethod
    def from_str(cls, val: Union[Severity, str]) -> Severity:
        """Coerces strings into Severity enum."""
        if isinstance(val, Severity):
            return val
        s = str(val).strip().upper()
        if s in ("WARN", "WARNING"):
            return cls.WARNING
        if s in ("ERR", "ERROR", "CRITICAL", "FATAL"):
            return cls.ERROR
        return cls.INFO


@dataclass
class ToastAction:
    """Action button rendered on the Windows Toast Notification."""
    content: str
    arguments: str
    activation_type: str = "protocol"  # "protocol", "foreground", or "background"

    def to_xml(self) -> str:
        """Renders the action XML element with properly escaped attributes."""
        esc_content = html.escape(self.content, quote=True)
        esc_args = html.escape(self.arguments, quote=True)
        esc_type = html.escape(self.activation_type, quote=True)
        return f'<action content="{esc_content}" arguments="{esc_args}" activationType="{esc_type}"/>'


@dataclass
class ToastNotification:
    """Represents a dispatched toast notification record."""
    title: str
    message: str
    severity: Severity
    actions: List[ToastAction] = field(default_factory=list)
    attribution: str = "Salesforce Jarvis"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    success: bool = False
    details: str = ""


# In-memory thread-safe notification history (useful for Cockpit HUD and test verifications)
_NOTIFICATION_LOCK = threading.Lock()
_NOTIFICATION_HISTORY: List[ToastNotification] = []
_MAX_HISTORY_SIZE = 100


def get_notification_history() -> List[ToastNotification]:
    """Returns a copy of the notification history log."""
    with _NOTIFICATION_LOCK:
        return list(_NOTIFICATION_HISTORY)


def clear_notification_history() -> None:
    """Clears the notification history."""
    with _NOTIFICATION_LOCK:
        _NOTIFICATION_HISTORY.clear()


def _record_notification(notif: ToastNotification) -> None:
    """Appends a notification record to the in-memory history log."""
    with _NOTIFICATION_LOCK:
        _NOTIFICATION_HISTORY.append(notif)
        if len(_NOTIFICATION_HISTORY) > _MAX_HISTORY_SIZE:
            _NOTIFICATION_HISTORY.pop(0)


def build_toast_xml(
    title: str,
    message: str,
    severity: Severity = Severity.INFO,
    actions: Optional[List[ToastAction]] = None,
    sound: bool = True,
    attribution: str = "Salesforce Jarvis",
    launch_arg: Optional[str] = None,
) -> str:
    """Constructs the WinRT Toast XML template.

    Args:
        title: Toast notification header.
        message: Toast notification body.
        severity: Severity enum (determines audio, badge, and urgency scenario).
        actions: Optional list of action buttons.
        sound: Whether audio chime should play.
        attribution: Small footer text (default: 'Salesforce Jarvis').
        launch_arg: Protocol or argument activated when user clicks the toast body.

    Returns:
        Formatted XML string.
    """
    actions = actions or []

    # Map severity to scenario, sound, and visual prefix
    if severity == Severity.ERROR:
        prefix = "🔴 "
        sound_source = "ms-winsoundevent:Notification.Looping.Alarm"
        scenario = 'scenario="urgent"'
    elif severity == Severity.WARNING:
        prefix = "🟡 "
        sound_source = "ms-winsoundevent:Notification.Reminder"
        scenario = 'scenario="default"'
    else:
        prefix = "🟢 "
        sound_source = "ms-winsoundevent:Notification.Default"
        scenario = 'scenario="default"'

    display_title = prefix + title if not title.startswith(("🔴", "🟡", "🟢", "🚨", "⚠️", "ℹ️")) else title
    esc_title = html.escape(display_title, quote=True)
    esc_message = html.escape(message, quote=True)
    esc_attrib = html.escape(attribution, quote=True)

    # Toast launch attribute (body click)
    launch_attr = f'launch="{html.escape(launch_arg, quote=True)}"' if launch_arg else ""

    # Audio node
    if sound:
        audio_node = f'<audio src="{sound_source}" silent="false"/>'
    else:
        audio_node = '<audio silent="true"/>'

    # Action buttons node
    if actions:
        actions_inner = "\n    ".join(act.to_xml() for act in actions)
        actions_node = f"<actions>\n    {actions_inner}\n</actions>"
    else:
        actions_node = ""

    xml_template = f"""<toast {scenario} {launch_attr}>
    <visual>
        <binding template="ToastGeneric">
            <text id="1">{esc_title}</text>
            <text id="2">{esc_message}</text>
            <text placement="attribution">{esc_attrib}</text>
        </binding>
    </visual>
    {audio_node}
    {actions_node}
</toast>"""

    return xml_template.strip()


def _dispatch_powershell_winrt(xml_string: str, app_id: str = "Salesforce Jarvis") -> bool:
    """Executes native WinRT toast dispatch via PowerShell using base64 UTF-16LE encoding.

    This avoids all command line argument escaping bugs on Windows.
    """
    ps_script = f"""
$ErrorActionPreference = 'Stop'
try {{
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml(@'
{xml_string}
'@)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app_id}').Show($toast)
    exit 0
}} catch {{
    # Fallback to standard PowerShell AppID if custom AppID fails
    try {{
        $standardAppId = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($standardAppId).Show($toast)
        exit 0
    }} catch {{
        [Console]::Error.WriteLine($_)
        exit 1
    }}
}}
"""
    # Encode as UTF-16LE Base64 for PowerShell -EncodedCommand
    encoded_cmd = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")

    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle", "Hidden",
                "-EncodedCommand", encoded_cmd,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        if proc.returncode == 0:
            return True
        logger.warning("PowerShell WinRT toast exited with code %d: %s", proc.returncode, proc.stderr.strip())
        return False
    except subprocess.TimeoutExpired:
        logger.warning("PowerShell WinRT toast timed out after 8s")
        return False
    except Exception as exc:
        logger.error("Failed to execute PowerShell WinRT toast: %s", exc)
        return False


def _dispatch_burnt_toast(
    title: str,
    message: str,
    severity: Severity = Severity.INFO,
    sound: bool = True,
) -> bool:
    """Attempts notification using BurntToast module if available."""
    sound_param = "" if sound else "-Silent"
    ps_cmd = (
        f"if (Get-Module -ListAvailable BurntToast) {{ "
        f"Import-Module BurntToast; "
        f"New-BurntToastNotification -Text '{title}', '{message}' -AppLogo '' {sound_param}; exit 0 "
        f"}} else {{ exit 2 }}"
    )
    encoded = base64.b64encode(ps_cmd.encode("utf-16le")).decode("ascii")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def send_toast(
    title: str,
    message: str,
    severity: Union[Severity, str] = Severity.INFO,
    actions: Optional[List[ToastAction]] = None,
    sound: bool = True,
    attribution: str = "Salesforce Jarvis",
    launch_arg: Optional[str] = None,
    wait: bool = False,
    dry_run: bool = False,
) -> bool:
    """Sends a native Windows Toast Notification.

    By default, dispatches asynchronously in a background worker thread
    to guarantee non-blocking performance for callers and GUI event loops.

    Args:
        title: Header text for the toast.
        message: Body description.
        severity: INFO, WARNING, or ERROR.
        actions: Interactive buttons (e.g. [ToastAction("Fix", "https://...")]).
        sound: Whether to play notification audio.
        attribution: Attribution footer text.
        launch_arg: Action/URL when user clicks toast body.
        wait: If True, blocks until PowerShell finishes and returns success boolean.
        dry_run: If True, records notification without invoking Windows OS APIs.

    Returns:
        True if successfully queued/sent, False on immediate failure.
    """
    sev = Severity.from_str(severity)
    actions = actions or []

    # Check environment variable override for headless test environments
    if dry_run or os.environ.get("JARVIS_NOTIFY_DRY_RUN", "").lower() in ("1", "true", "yes"):
        record = ToastNotification(
            title=title,
            message=message,
            severity=sev,
            actions=actions,
            attribution=attribution,
            success=True,
            details="dry_run_recorded",
        )
        _record_notification(record)
        logger.info("[DRY_RUN NOTIFICATION] [%s] %s: %s", sev.value, title, message)
        return True

    xml_content = build_toast_xml(
        title=title,
        message=message,
        severity=sev,
        actions=actions,
        sound=sound,
        attribution=attribution,
        launch_arg=launch_arg,
    )

    def _execute() -> bool:
        # Tier 1: Native WinRT via PowerShell
        ok = _dispatch_powershell_winrt(xml_content)
        # Tier 2: BurntToast fallback if WinRT failed
        if not ok:
            ok = _dispatch_burnt_toast(title, message, sev, sound)

        status_msg = "dispatched_winrt" if ok else "failed_all_providers"
        record = ToastNotification(
            title=title,
            message=message,
            severity=sev,
            actions=actions,
            attribution=attribution,
            success=ok,
            details=status_msg,
        )
        _record_notification(record)
        return ok

    if wait:
        return _execute()
    else:
        # Non-blocking async dispatch
        t = threading.Thread(target=_execute, name="JarvisToastWorker", daemon=True)
        t.start()
        return True


# =====================================================================
# Specialized Domain Notification Helpers for Salesforce Jarvis
# =====================================================================

def notify_salesforce_issue(
    org_name: str,
    issue_description: str,
    severity: Union[Severity, str] = Severity.ERROR,
    action_url: Optional[str] = None,
    wait: bool = False,
) -> bool:
    """Dispatches an alert when a Salesforce architecture conflict or runtime error occurs."""
    sev = Severity.from_str(severity)
    actions: List[ToastAction] = []
    if action_url:
        actions.append(ToastAction(content="View in Salesforce", arguments=action_url))
    actions.append(ToastAction(content="Open Cockpit", arguments="https://localhost:8000"))

    title = f"Salesforce Conflict: {org_name}"
    return send_toast(
        title=title,
        message=issue_description,
        severity=sev,
        actions=actions,
        attribution=f"Salesforce Jarvis • {org_name}",
        launch_arg=action_url or "https://localhost:8000",
        wait=wait,
    )


def notify_batch_failure(
    job_name: str,
    error_msg: str,
    job_id: Optional[str] = None,
    org_name: Optional[str] = None,
    action_url: Optional[str] = None,
    wait: bool = False,
) -> bool:
    """Dispatches a critical toast alert when an Apex Batch or Queueable job fails."""
    org_label = f" ({org_name})" if org_name else ""
    title = f"Apex Batch Failure{org_label}"
    msg_body = f"Job '{job_name}' failed"
    if job_id:
        msg_body += f" [ID: {job_id}]"
    msg_body += f": {error_msg}"

    actions: List[ToastAction] = []
    if action_url:
        actions.append(ToastAction(content="Inspect Job", arguments=action_url))
    actions.append(ToastAction(content="Open Cockpit", arguments="https://localhost:8000"))

    return send_toast(
        title=title,
        message=msg_body,
        severity=Severity.ERROR,
        actions=actions,
        attribution=f"Salesforce Jarvis • Async Apex Monitor",
        launch_arg=action_url,
        wait=wait,
    )


def notify_governor_limit_warning(
    component_name: str,
    metric_name: str,
    usage_pct: float,
    limit_max: int,
    org_name: Optional[str] = None,
    wait: bool = False,
) -> bool:
    """Dispatches a warning toast when governor limits approach threshold."""
    org_label = f" • {org_name}" if org_name else ""
    title = f"Governor Limit Warning ({usage_pct:.0f}%)"
    message = (
        f"{component_name} consumed {usage_pct:.0f}% of maximum {metric_name} "
        f"(Limit: {limit_max}). Risk of System.LimitException."
    )
    return send_toast(
        title=title,
        message=message,
        severity=Severity.WARNING,
        actions=[ToastAction(content="Run Conflict Radar", arguments="https://localhost:8000")],
        attribution=f"Salesforce Jarvis{org_label}",
        wait=wait,
    )


def notify_nominal_health(
    org_name: Optional[str] = None,
    summary: str = "All monitored Salesforce orgs, batch jobs, and triggers nominal.",
    wait: bool = False,
) -> bool:
    """Dispatches an informational toast confirming system health."""
    org_label = f": {org_name}" if org_name else ""
    title = f"System Nominal{org_label}"
    return send_toast(
        title=title,
        message=summary,
        severity=Severity.INFO,
        attribution="Salesforce Jarvis • Monitor Daemon",
        wait=wait,
    )


def main() -> int:
    """CLI testing helper for desktop notifications."""
    import argparse

    parser = argparse.ArgumentParser(description="Send test notifications via Salesforce Jarvis")
    parser.add_argument("--title", default="Salesforce Jarvis Alert", help="Notification title")
    parser.add_argument("--message", default="Apex execution test message.", help="Notification message")
    parser.add_argument("--severity", choices=["INFO", "WARNING", "ERROR"], default="INFO", help="Severity level")
    parser.add_argument("--action-url", default="https://developer.salesforce.com", help="Action button URL")
    parser.add_argument("--wait", action="store_true", help="Wait for notification delivery")
    args = parser.parse_args()

    actions = [ToastAction(content="Open Action", arguments=args.action_url)] if args.action_url else None
    ok = send_toast(
        title=args.title,
        message=args.message,
        severity=args.severity,
        actions=actions,
        wait=args.wait,
    )
    print(f"Toast dispatched successfully: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
