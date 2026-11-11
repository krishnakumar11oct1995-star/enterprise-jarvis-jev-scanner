"""Enterprise Jarvis Desktop HUD Window Manager & Launcher.

Runs the local FastAPI backend server, opens a sleek glassmorphic desktop window
via pywebview or native browser app mode, and registers global hotkey Alt + J
to toggle HUD visibility.
"""

from __future__ import annotations
import os
import sys
import time
import socket
import logging
import argparse
import threading
import subprocess
from pathlib import Path
from typing import Optional, Callable

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ui.server import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("jarvis.hud")


def find_available_port(start_port: int = 8765, max_attempts: int = 20) -> int:
    """Finds an open TCP port on localhost starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            result = sock.connect_ex(("127.0.0.1", port))
            if result != 0:  # Port is available
                return port
    return start_port


class DesktopHUD:
    """Desktop Window Manager and Global Hotkey Coordinator."""

    def __init__(
        self,
        port: int = 8765,
        browser_mode: bool = False,
        no_window: bool = False,
        title: str = "JARVIS // ENTERPRISE ARCHITECTURE COCKPIT",
        width: int = 1320,
        height: int = 860,
    ):
        self.port = find_available_port(port)
        self.browser_mode = browser_mode
        self.no_window = no_window
        self.title = title
        self.width = width
        self.height = height

        self.server_url = f"http://127.0.0.1:{self.port}"
        self.is_visible = True
        self.webview_window = None
        self.browser_proc = None
        self.server_thread = None
        self.hotkey_registered = False
        self._shutdown_event = threading.Event()

    def start_server(self):
        """Starts the FastAPI HTTP backend using Uvicorn in a daemon thread."""
        import uvicorn

        app = create_app(window_manager_callback=self.handle_window_action)

        class UvicornServer(uvicorn.Server):
            def install_signal_handlers(self):
                pass

        config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        server = UvicornServer(config=config)
        self.server_thread = threading.Thread(target=server.run, daemon=True, name="JarvisUvicornThread")
        self.server_thread.start()

        # Wait briefly for server socket readiness
        time.sleep(0.6)
        logger.info(f"[HUD] Jarvis Cockpit server active at {self.server_url}")

    def register_global_hotkey(self):
        """Registers the global hotkey 'Alt + J' to toggle HUD visibility."""
        hotkey_str = "alt+j"

        # Strategy A: Use keyboard package
        try:
            import keyboard

            keyboard.add_hotkey(hotkey_str, self.toggle_visibility, suppress=False)
            self.hotkey_registered = True
            logger.info(f"[HOTKEY] Global Hotkey registered: [{hotkey_str.upper()}] via keyboard library")
            return
        except Exception as e:
            logger.warning(f"Could not hook keyboard driver directly ({e}). Attempting Windows RegisterHotKey fallback...")

        # Strategy B: Windows RegisterHotKey API via ctypes
        if sys.platform == "win32":
            try:
                self._start_win32_hotkey_thread()
                self.hotkey_registered = True
                logger.info("[HOTKEY] Global Hotkey registered: [ALT + J] via Windows RegisterHotKey API")
                return
            except Exception as e:
                logger.warning(f"Windows RegisterHotKey fallback failed: {e}")

        logger.warning("Global hotkey could not be bound in this environment. In-browser shortcuts will be active.")

    def _start_win32_hotkey_thread(self):
        """Background thread running Windows GetMessage message pump for RegisterHotKey."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        MOD_ALT = 0x0001
        VK_J = 0x4A
        HOTKEY_ID = 1001

        def hotkey_loop():
            # Register hotkey for current thread
            if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_ALT, VK_J):
                logger.error("RegisterHotKey call returned False")
                return

            msg = wintypes.MSG()
            while not self._shutdown_event.is_set():
                # Peek or GetMessage
                if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE = 1
                    if msg.message == 0x0312:  # WM_HOTKEY
                        if msg.wParam == HOTKEY_ID:
                            self.toggle_visibility()
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.05)

            user32.UnregisterHotKey(None, HOTKEY_ID)

        t = threading.Thread(target=hotkey_loop, daemon=True, name="Win32HotkeyListener")
        t.start()

    def toggle_visibility(self):
        """Toggles HUD desktop window between visible and hidden/minimized."""
        logger.info(f"⚡ [Alt + J] Hotkey triggered! Current state: {'VISIBLE' if self.is_visible else 'HIDDEN'}")

        if self.webview_window:
            try:
                if self.is_visible:
                    # Hide or minimize
                    try:
                        self.webview_window.minimize()
                    except Exception:
                        self.webview_window.hide()
                    self.is_visible = False
                    logger.info("HUD window minimized/hidden")
                else:
                    # Show and restore
                    try:
                        self.webview_window.restore()
                    except Exception:
                        self.webview_window.show()
                    self.is_visible = True
                    logger.info("HUD window restored to foreground")
                return
            except Exception as e:
                logger.error(f"Error toggling pywebview window: {e}")

        # Native Windows window fallback
        if sys.platform == "win32":
            try:
                import win32gui
                import win32con

                # Find window by title
                hwnd = win32gui.FindWindow(None, self.title)
                if not hwnd:
                    # Look for Edge app window containing title
                    def callback(h, extra):
                        txt = win32gui.GetWindowText(h)
                        if "JARVIS" in txt or "Enterprise Architecture" in txt:
                            extra.append(h)
                    windows = []
                    win32gui.EnumWindows(callback, windows)
                    if windows:
                        hwnd = windows[0]

                if hwnd:
                    if self.is_visible:
                        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                        self.is_visible = False
                        logger.info("HUD window minimized via Win32")
                    else:
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(hwnd)
                        self.is_visible = True
                        logger.info("HUD window brought to foreground via Win32")
            except Exception as e:
                logger.warning(f"Win32 toggle fallback error: {e}")

    def handle_window_action(self, action: str) -> str:
        """Processes window actions triggered via UI REST calls."""
        if action == "toggle":
            self.toggle_visibility()
            return "toggled"
        elif action == "minimize":
            if self.webview_window:
                self.webview_window.minimize()
            self.is_visible = False
            return "minimized"
        elif action == "show":
            if self.webview_window:
                self.webview_window.restore()
            self.is_visible = True
            return "shown"
        elif action == "quit":
            self.shutdown()
            return "shutdown"
        return "unknown"

    def launch_browser_app(self):
        """Launches native modern browser in frameless standalone app mode."""
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]

        browser_exe = None
        for p in edge_paths + chrome_paths:
            if os.path.exists(p):
                browser_exe = p
                break

        if browser_exe:
            cmd = [
                browser_exe,
                f"--app={self.server_url}",
                f"--window-size={self.width},{self.height}",
                "--disable-infobars",
                "--disable-extensions",
            ]
            logger.info(f"Launching sleek browser app window: {browser_exe}")
            self.browser_proc = subprocess.Popen(cmd)
        else:
            import webbrowser
            logger.info(f"Opening default browser at {self.server_url}")
            webbrowser.open(self.server_url)

    def launch_webview(self):
        """Launches a desktop window using pywebview."""
        import webview

        self.webview_window = webview.create_window(
            title=self.title,
            url=self.server_url,
            width=self.width,
            height=self.height,
            resizable=True,
            easy_drag=False,
            background_color="#080c14",
            text_select=True,
        )
        logger.info("Starting pywebview native window loop...")
        webview.start(debug=False)

    def run(self):
        """Main lifecycle entrypoint for Desktop HUD."""
        # 1. Start HTTP Server
        self.start_server()

        # 2. Register Global Hotkey
        self.register_global_hotkey()

        # 3. Launch UI Window
        if self.no_window:
            logger.info("Running in headless server mode (--no-window). Press Ctrl+C to terminate.")
            try:
                while not self._shutdown_event.is_set():
                    time.sleep(1)
            except KeyboardInterrupt:
                self.shutdown()
            return

        if self.browser_mode:
            self.launch_browser_app()
            logger.info("HUD launched in native app browser mode. Press Ctrl+C in terminal to exit.")
            try:
                while not self._shutdown_event.is_set():
                    time.sleep(1)
            except KeyboardInterrupt:
                self.shutdown()
            return

        # Attempt pywebview first
        try:
            self.launch_webview()
        except Exception as e:
            logger.warning(f"pywebview GUI failed to initialize ({e}). Falling back to native browser app mode...")
            self.launch_browser_app()
            try:
                while not self._shutdown_event.is_set():
                    time.sleep(1)
            except KeyboardInterrupt:
                self.shutdown()

    def shutdown(self):
        """Clean graceful shutdown."""
        logger.info("Shutting down Project Jarvis HUD...")
        self._shutdown_event.set()
        if self.browser_proc:
            try:
                self.browser_proc.terminate()
            except Exception:
                pass


def launch_hud(
    port: int = 8765,
    browser: bool = False,
    no_window: bool = False,
):
    """Programmatic entrypoint to start the Jarvis Desktop HUD."""
    hud = DesktopHUD(
        port=port,
        browser_mode=browser,
        no_window=no_window,
    )
    hud.run()


def main():
    """CLI entrypoint for app.ui.hud."""
    parser = argparse.ArgumentParser(
        prog="jarvis-hud",
        description="Project Jarvis: Desktop HUD Cockpit UI",
    )
    parser.add_argument("--port", type=int, default=8765, help="Port for HUD server (default: 8765)")
    parser.add_argument("--browser", action="store_true", help="Force native browser app mode instead of pywebview")
    parser.add_argument("--no-window", action="store_true", help="Start background server only without desktop window")

    args = parser.parse_args()
    launch_hud(
        port=args.port,
        browser=args.browser,
        no_window=args.no_window,
    )


if __name__ == "__main__":
    main()
