"""Salesforce Jarvis Desktop Application Package.

Milestone 1 Deliverables:
- startup: Windows Boot Auto-start and verification.
- notify: Native Windows Toast Notifications and domain alerts.
- tray: Dynamic System Tray Daemon with context menus and HUD toggling.
"""

from app.startup import (
    register_startup,
    unregister_startup,
    is_startup_enabled,
    verify_startup,
    toggle_startup,
    generate_vbs_script,
    get_startup_dir,
    get_pythonw_executable,
)

from app.notify import (
    Severity,
    ToastAction,
    ToastNotification,
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

from app.voice import (
    VoiceEngine,
    get_voice_engine,
    ExecutiveBriefing,
    run_executive_briefing,
    DEFAULT_VOICE,
)

from app.sf_poller import (
    SalesforcePoller,
    SalesforceCLI,
    extract_json_from_cli_output,
)

__all__ = [
    # Startup
    "register_startup",
    "unregister_startup",
    "is_startup_enabled",
    "verify_startup",
    "toggle_startup",
    "generate_vbs_script",
    "get_startup_dir",
    "get_pythonw_executable",
    # Notify
    "Severity",
    "ToastAction",
    "ToastNotification",
    "send_toast",
    "notify_salesforce_issue",
    "notify_batch_failure",
    "notify_governor_limit_warning",
    "notify_nominal_health",
    "get_notification_history",
    "clear_notification_history",
    # Tray
    "TrayStatus",
    "JarvisTrayDaemon",
    "render_status_icon",
    # Voice & Executive Briefing
    "VoiceEngine",
    "get_voice_engine",
    "ExecutiveBriefing",
    "run_executive_briefing",
    "DEFAULT_VOICE",
    # SF Poller
    "SalesforcePoller",
    "SalesforceCLI",
    "extract_json_from_cli_output",
]
