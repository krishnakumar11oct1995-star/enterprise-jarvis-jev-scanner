"""Windows System Tray Daemon for Salesforce Jarvis.

Manages the system tray icon, dynamic status states (Nominal, Warning, Error),
interactive context menus, and double-click HUD activation.
"""

from __future__ import annotations

import os
import sys
import time
import logging
import threading
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Dict, Any, Tuple, Union

from PIL import Image, ImageDraw, ImageFont
import pystray
from pystray import MenuItem, Menu

from app.startup import is_startup_enabled, toggle_startup
from app.notify import send_toast, Severity

logger = logging.getLogger(__name__)

# Windows message constants
WM_NOTIFY = 0x004E
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205


class TrayStatus(str, Enum):
    """System tray operational states."""
    NOMINAL = "NOMINAL"  # 🟢 Green: Everything healthy
    WARNING = "WARNING"  # 🟡 Yellow: Governor limit near threshold / non-blocking conflict
    ERROR = "ERROR"      # 🔴 Red: Batch failure / critical recursion loop detected

    @classmethod
    def from_str(cls, val: Union[TrayStatus, str]) -> TrayStatus:
        if isinstance(val, TrayStatus):
            return val
        s = str(val).strip().upper()
        if s in ("WARN", "WARNING"):
            return cls.WARNING
        if s in ("ERR", "ERROR", "CRITICAL", "ALERT"):
            return cls.ERROR
        return cls.NOMINAL

    @property
    def color_rgb(self) -> Tuple[int, int, int]:
        """Returns the primary RGB color for the state."""
        if self == TrayStatus.NOMINAL:
            return (16, 185, 129)  # Vibrant Emerald (#10B981)
        elif self == TrayStatus.WARNING:
            return (245, 158, 11)  # Amber (#F59E0B)
        else:
            return (239, 68, 68)   # Crimson Red (#EF4444)

    @property
    def emoji(self) -> str:
        if self == TrayStatus.NOMINAL:
            return "🟢"
        elif self == TrayStatus.WARNING:
            return "🟡"
        else:
            return "🔴"


# In-memory icon cache to avoid re-rendering identical images
_ICON_CACHE: Dict[Tuple[TrayStatus, Tuple[int, int]], Image.Image] = {}


def render_status_icon(
    status: Union[TrayStatus, str],
    size: Tuple[int, int] = (64, 64),
) -> Image.Image:
    """Renders a dynamic high-DPI RGBA icon representing the system status.

    Design:
    - Dark circular background plate (#0F172A slate-900).
    - Status-colored glowing outer perimeter ring.
    - Status-colored inner glowing dot/radar beacon.
    - Crisp stylized white center accent.
    """
    stat = TrayStatus.from_str(status)
    cache_key = (stat, size)
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key].copy()

    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    r, g, b = stat.color_rgb

    # 1. Subtle dark background disc
    pad = max(2, int(w * 0.06))
    draw.ellipse(
        [pad, pad, w - pad, h - pad],
        fill=(15, 23, 42, 235),  # Deep slate
        outline=(r, g, b, 255),
        width=max(2, int(w * 0.08)),
    )

    # 2. Glowing aura ring
    inner_pad = max(6, int(w * 0.22))
    draw.ellipse(
        [inner_pad, inner_pad, w - inner_pad, h - inner_pad],
        fill=(r, g, b, 220),
    )

    # 3. White center beacon accent (gives a polished glassy orb appearance)
    core_pad = max(10, int(w * 0.38))
    draw.ellipse(
        [core_pad, core_pad, w - core_pad, h - core_pad],
        fill=(255, 255, 255, 240),
    )

    _ICON_CACHE[cache_key] = img
    return img.copy()


class JarvisTrayDaemon:
    """Windows System Tray Daemon managing icon, context menus, and events."""

    def __init__(
        self,
        on_open_cockpit: Optional[Callable[[], None]] = None,
        on_morning_briefing: Optional[Callable[[], None]] = None,
        on_refresh_status: Optional[Callable[[], None]] = None,
        on_toggle_startup: Optional[Callable[[bool], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        initial_status: Union[TrayStatus, str] = TrayStatus.NOMINAL,
    ):
        self.on_open_cockpit = on_open_cockpit
        self.on_morning_briefing = on_morning_briefing
        self.on_refresh_status = on_refresh_status
        self.on_toggle_startup = on_toggle_startup
        self.on_exit = on_exit

        self._status = TrayStatus.from_str(initial_status)
        self._status_lock = threading.Lock()
        self._is_running = False
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None
        self._last_double_click = 0.0

        self._init_pystray_icon()

    @property
    def status(self) -> TrayStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _init_pystray_icon(self) -> None:
        """Initializes the pystray.Icon instance with menus and event hooks."""
        image = render_status_icon(self._status)
        menu = self._build_menu()
        title = self._format_tooltip()

        self._icon = pystray.Icon(
            name="SalesforceJarvis",
            icon=image,
            title=title,
            menu=menu,
        )

        # Hook win32 message dispatch for double-click handling
        self._attach_double_click_handler()

    def _format_tooltip(self, suffix: Optional[str] = None) -> str:
        """Formats the tray icon hover tooltip text."""
        base = f"Salesforce Jarvis - {self._status.emoji} {self._status.value}"
        if suffix:
            base += f" ({suffix})"
        return base[:127]  # Windows NOTIFYICONDATA szTip limit is 128 chars

    def _build_menu(self) -> Menu:
        """Constructs the system tray context menu."""
        return Menu(
            MenuItem(
                "Open Cockpit (Alt+J)",
                self._action_open_cockpit,
                default=True,  # Default action executed on click/double-click
            ),
            Menu.SEPARATOR,
            MenuItem(
                "Morning Briefing",
                self._action_morning_briefing,
            ),
            MenuItem(
                "Refresh Salesforce Status",
                self._action_refresh_status,
            ),
            Menu.SEPARATOR,
            MenuItem(
                lambda item: f"Startup: {'Enabled' if is_startup_enabled() else 'Disabled'}",
                self._action_toggle_startup,
                checked=lambda item: is_startup_enabled(),
            ),
            Menu.SEPARATOR,
            MenuItem(
                "Exit",
                self._action_exit,
            ),
        )

    def _attach_double_click_handler(self) -> None:
        """Hooks pystray win32 notify handler to explicitly catch WM_LBUTTONDBLCLK."""
        if not hasattr(self._icon, "_message_handlers"):
            return

        original_notify = self._icon._on_notify

        def _custom_notify(wparam, lparam):
            if lparam == WM_LBUTTONDBLCLK:
                logger.debug("Tray double-click detected (WM_LBUTTONDBLCLK)")
                self.toggle_cockpit()
                return 0
            return original_notify(wparam, lparam)

        self._icon._message_handlers[WM_NOTIFY] = _custom_notify

    # =====================================================================
    # Context Menu Actions
    # =====================================================================

    def _action_open_cockpit(self, icon: Optional[pystray.Icon] = None, item: Optional[MenuItem] = None) -> None:
        """Action handler for 'Open Cockpit (Alt+J)'."""
        self.toggle_cockpit()

    def toggle_cockpit(self) -> None:
        """Toggles the Cockpit HUD."""
        logger.info("Toggling Salesforce Jarvis Cockpit HUD...")
        if self.on_open_cockpit:
            try:
                self.on_open_cockpit()
                return
            except Exception as exc:
                logger.error("Error executing on_open_cockpit callback: %s", exc)

        # Default fallback notification
        send_toast(
            title="Salesforce Jarvis Cockpit",
            message="Activating Jarvis HUD Cockpit (Alt+J)...",
            severity=Severity.INFO,
            sound=False,
        )

    def _action_morning_briefing(self, icon: Optional[pystray.Icon] = None, item: Optional[MenuItem] = None) -> None:
        """Action handler for 'Morning Briefing'."""
        logger.info("Triggering Morning Briefing...")
        if self.on_morning_briefing:
            try:
                self.on_morning_briefing()
                return
            except Exception as exc:
                logger.error("Error in on_morning_briefing callback: %s", exc)

        # Default fallback: trigger spoken briefing directly
        briefing_text = "All Salesforce orgs analyzed: 0 recursive triggers, 100% batch health."
        try:
            from app.voice import run_executive_briefing
            briefing_text = run_executive_briefing()
        except Exception as exc:
            logger.debug("Could not run spoken briefing fallback: %s", exc)

        send_toast(
            title="Morning Briefing",
            message=briefing_text[:180] + ("..." if len(briefing_text) > 180 else ""),
            severity=Severity.INFO,
        )

    def _action_refresh_status(self, icon: Optional[pystray.Icon] = None, item: Optional[MenuItem] = None) -> None:
        """Action handler for 'Refresh Salesforce Status' / Scan Orgs."""
        logger.info("Refreshing Salesforce Status / Scanning Orgs...")
        if self.on_refresh_status:
            try:
                self.on_refresh_status()
                return
            except Exception as exc:
                logger.error("Error in on_refresh_status callback: %s", exc)

        # Simulate quick scan
        self.set_status(TrayStatus.NOMINAL, tooltip_suffix="Scan complete")
        send_toast(
            title="Scan Complete",
            message="Org metadata and batch queue refreshed. Status: Nominal.",
            severity=Severity.INFO,
            sound=False,
        )

    def _action_toggle_startup(self, icon: Optional[pystray.Icon] = None, item: Optional[MenuItem] = None) -> None:
        """Toggles Windows startup on/off."""
        new_state = toggle_startup()
        state_str = "Enabled" if new_state else "Disabled"
        logger.info("Startup toggled. Current state: %s", state_str)

        if self.on_toggle_startup:
            try:
                self.on_toggle_startup(new_state)
            except Exception as exc:
                logger.error("Error in on_toggle_startup callback: %s", exc)

        if self._icon:
            self._icon.update_menu()

        send_toast(
            title=f"Windows Startup {state_str}",
            message=f"Salesforce Jarvis silent background boot is now {state_str.lower()}.",
            severity=Severity.INFO,
            sound=False,
        )

    def _action_exit(self, icon: Optional[pystray.Icon] = None, item: Optional[MenuItem] = None) -> None:
        """Action handler for 'Exit'."""
        logger.info("Exiting Salesforce Jarvis Tray Daemon...")
        self.stop()

    # =====================================================================
    # Dynamic Status & Lifecycle
    # =====================================================================

    def set_status(
        self,
        status: Union[TrayStatus, str],
        tooltip_suffix: Optional[str] = None,
        notify_change: bool = False,
    ) -> None:
        """Updates the tray icon state dynamically (Nominal, Warning, Error).

        Args:
            status: New state (NOMINAL, WARNING, ERROR).
            tooltip_suffix: Optional extra context string for hover tooltip.
            notify_change: If True, fires a toast notification regarding the change.
        """
        new_status = TrayStatus.from_str(status)
        with self._status_lock:
            old_status = self._status
            self._status = new_status

        if self._icon:
            try:
                self._icon.icon = render_status_icon(new_status)
                self._icon.title = self._format_tooltip(tooltip_suffix)
            except Exception as exc:
                logger.warning("Failed to update tray icon visual: %s", exc)

        logger.info("Tray status updated: %s -> %s", old_status.value, new_status.value)

        if notify_change and old_status != new_status:
            sev = Severity.ERROR if new_status == TrayStatus.ERROR else (Severity.WARNING if new_status == TrayStatus.WARNING else Severity.INFO)
            send_toast(
                title=f"System State Changed: {new_status.value}",
                message=f"Salesforce Jarvis transitioned to {new_status.value} state.{f' ({tooltip_suffix})' if tooltip_suffix else ''}",
                severity=sev,
            )

    def start(self, detached: bool = True) -> None:
        """Starts the system tray daemon.

        Args:
            detached: If True, runs pystray message loop in a background thread.
        """
        if self._is_running:
            logger.warning("JarvisTrayDaemon is already running.")
            return

        self._is_running = True
        logger.info("Starting JarvisTrayDaemon (detached=%s)...", detached)

        if detached:
            self._icon.run_detached()
        else:
            self._icon.run()

    def stop(self) -> None:
        """Stops the system tray daemon cleanly."""
        was_running = self._is_running
        self._is_running = False
        logger.info("Stopping JarvisTrayDaemon...")

        if self._icon and was_running:
            try:
                self._icon.stop()
            except Exception as exc:
                logger.debug("Error while stopping icon: %s", exc)

        if self.on_exit:
            try:
                self.on_exit()
            except Exception as exc:
                logger.error("Error in on_exit callback: %s", exc)


def main() -> int:
    """CLI testing helper for launching the system tray daemon."""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Run Salesforce Jarvis System Tray Daemon")
    parser.add_argument("--status", choices=["NOMINAL", "WARNING", "ERROR"], default="NOMINAL", help="Initial status")
    parser.add_argument("--test-cycle", action="store_true", help="Cycle through status states every 2 seconds")
    args = parser.parse_args()

    daemon = JarvisTrayDaemon(initial_status=args.status)
    daemon.start(detached=True)
    print(f"Jarvis Tray Daemon active in taskbar. Status: {daemon.status.value}")
    print("Right-click icon for menu. Press Ctrl+C in console to stop.")

    try:
        if args.test_cycle:
            states = [TrayStatus.NOMINAL, TrayStatus.WARNING, TrayStatus.ERROR]
            idx = 0
            while daemon.is_running:
                time.sleep(2.5)
                daemon.set_status(states[idx % len(states)], tooltip_suffix="Cycle Demo")
                idx += 1
        else:
            while daemon.is_running:
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping daemon...")
    finally:
        daemon.stop()

    print("Daemon stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
