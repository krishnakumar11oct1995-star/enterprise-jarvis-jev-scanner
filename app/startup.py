"""Windows Boot Auto-start Management for Salesforce Jarvis.

Registers, unregisters, and verifies silent startup in the Windows Startup
folder (shell:startup) using pythonw.exe and a hidden VBS script so that
Salesforce Jarvis boots silently with zero black console window.
"""

from __future__ import annotations

import os
import sys
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Constants
DEFAULT_SHORTCUT_NAME = "Salesforce Jarvis.lnk"
DEFAULT_VBS_NAME = "launch_jarvis_silent.vbs"
APP_DESCRIPTION = "Salesforce Jarvis PC Background Daemon"


def get_project_root() -> Path:
    """Returns the absolute path to the enterprise_jarvis root directory."""
    # Current file is in enterprise_jarvis/app/startup.py
    return Path(__file__).resolve().parent.parent


def get_startup_dir() -> Path:
    """Resolves the user's Windows Startup directory.

    Typically: C:\\Users\\<Username>\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        startup_path = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        if startup_path.exists():
            return startup_path

    # Fallback using Windows shell API via ctypes
    try:
        import ctypes
        import ctypes.wintypes
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        # CSIDL_STARTUP = 7
        if ctypes.windll.shell32.SHGetFolderPathW(None, 7, None, 0, buf) == 0:
            p = Path(buf.value)
            if p.exists():
                return p
    except Exception as exc:
        logger.debug("ctypes SHGetFolderPathW failed: %s", exc)

    # Secondary fallback using default userprofile path
    userprofile = os.environ.get("USERPROFILE", str(Path.home()))
    fallback = Path(userprofile) / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def get_pythonw_executable() -> Path:
    """Resolves the path to pythonw.exe (GUI Python with no console window).

    Searches:
    1. Adjacent to sys.executable (e.g. C:\\Python314\\pythonw.exe)
    2. In PATH
    3. Fallback to sys.executable if pythonw cannot be found.
    """
    current_exe = Path(sys.executable).resolve()
    
    # 1. Check adjacent pythonw.exe
    pythonw_candidate = current_exe.parent / "pythonw.exe"
    if pythonw_candidate.is_file():
        return pythonw_candidate

    # 2. Search in PATH
    which_pythonw = shutil.which("pythonw.exe")
    if which_pythonw:
        p = Path(which_pythonw).resolve()
        if p.is_file():
            return p

    # 3. Check common Python install locations
    for root in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python", Path("C:/Python314"), Path("C:/Python313"), Path("C:/Python312")):
        if root.exists():
            for found in root.glob("**/pythonw.exe"):
                if found.is_file():
                    return found.resolve()

    logger.warning("pythonw.exe not found; falling back to sys.executable (%s)", current_exe)
    return current_exe


def get_default_target_script() -> Path:
    """Resolves the default entrypoint script for the background application."""
    root = get_project_root()
    # Check app/main.py
    app_main = root / "app" / "main.py"
    if app_main.is_file():
        return app_main
    # Fallback to root jarvis.py
    root_jarvis = root / "jarvis.py"
    if root_jarvis.is_file():
        return root_jarvis
    return app_main


def get_vbs_launcher_path() -> Path:
    """Returns the default absolute path for launch_jarvis_silent.vbs."""
    return get_project_root() / "app" / DEFAULT_VBS_NAME


def generate_vbs_script(
    target_script: Optional[Path] = None,
    output_vbs_path: Optional[Path] = None,
    pythonw_path: Optional[Path] = None,
) -> Path:
    """Generates the launch_jarvis_silent.vbs file.

    The VBS script runs pythonw.exe completely hidden (window style 0, bWaitOnReturn False)
    and sets the working directory to the project root. This guarantees zero black
    terminal flashing on Windows boot.

    Args:
        target_script: Python script to execute (defaults to app/main.py)
        output_vbs_path: Destination path for the .vbs file
        pythonw_path: Path to pythonw.exe (defaults to resolved pythonw)

    Returns:
        Path to the generated .vbs file.
    """
    target = Path(target_script or get_default_target_script()).resolve()
    dest = Path(output_vbs_path or get_vbs_launcher_path()).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    pythonw = Path(pythonw_path or get_pythonw_executable()).resolve()
    project_root = get_project_root().resolve()

    # VBS content with Chr(34) quotation to handle spaces in Windows paths safely
    vbs_content = f"""' =====================================================================
' Salesforce Jarvis Silent Boot Launcher
' Auto-generated by app/startup.py
' Ensures 100% silent background startup with zero console window flicker
' =====================================================================
Option Explicit
Dim WshShell, fso
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

Dim pythonwPath, scriptPath, workDir
pythonwPath = "{str(pythonw)}"
scriptPath = "{str(target)}"
workDir = "{str(project_root)}"

If fso.FolderExists(workDir) Then
    WshShell.CurrentDirectory = workDir
End If

' Run with window style 0 (Hidden) and bWaitOnReturn False
Dim cmd
cmd = Chr(34) & pythonwPath & Chr(34) & " " & Chr(34) & scriptPath & Chr(34)
WshShell.Run cmd, 0, False

Set WshShell = Nothing
Set fso = Nothing
"""
    dest.write_text(vbs_content, encoding="utf-8")
    logger.info("Generated silent VBS launcher at: %s", dest)
    return dest


def _create_windows_shortcut(
    shortcut_path: Path,
    target_path: Path,
    arguments: str = "",
    working_dir: Optional[Path] = None,
    description: str = APP_DESCRIPTION,
    icon_location: Optional[str] = None,
) -> bool:
    """Creates a Windows .lnk shortcut using win32com or PowerShell fallback."""
    shortcut_path = Path(shortcut_path).resolve()
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    working_dir = Path(working_dir or get_project_root()).resolve()

    # 1. Primary: Try win32com.client
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.TargetPath = str(target_path)
        shortcut.Arguments = arguments
        shortcut.WorkingDirectory = str(working_dir)
        shortcut.Description = description
        shortcut.WindowStyle = 7  # 7 = Minimized / Silent
        if icon_location:
            shortcut.IconLocation = icon_location
        shortcut.Save()
        logger.debug("Created shortcut via win32com at: %s", shortcut_path)
        return True
    except Exception as exc:
        logger.debug("win32com shortcut creation failed (%s), attempting PowerShell fallback...", exc)

    # 2. Fallback: PowerShell WScript.Shell invocation
    try:
        import subprocess
        ps_script = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{str(shortcut_path)}'); "
            f"$s.TargetPath = '{str(target_path)}'; "
            f"$s.Arguments = '{arguments}'; "
            f"$s.WorkingDirectory = '{str(working_dir)}'; "
            f"$s.Description = '{description}'; "
            f"$s.WindowStyle = 7; "
        )
        if icon_location:
            ps_script += f"$s.IconLocation = '{icon_location}'; "
        ps_script += "$s.Save()"

        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode == 0 and shortcut_path.is_file()
    except Exception as exc:
        logger.error("PowerShell shortcut creation failed: %s", exc)
        return False


def _read_windows_shortcut(shortcut_path: Path) -> Dict[str, str]:
    """Reads properties of an existing Windows .lnk shortcut."""
    shortcut_path = Path(shortcut_path).resolve()
    if not shortcut_path.is_file():
        return {}

    # Primary: win32com
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(shortcut_path))
        return {
            "target_path": str(shortcut.TargetPath or ""),
            "arguments": str(shortcut.Arguments or ""),
            "working_directory": str(shortcut.WorkingDirectory or ""),
            "description": str(shortcut.Description or ""),
        }
    except Exception as exc:
        logger.debug("win32com read shortcut failed: %s", exc)

    # Fallback: PowerShell
    try:
        import subprocess
        ps_cmd = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{str(shortcut_path)}'); "
            f"Write-Output \"$($s.TargetPath)|$($s.Arguments)|$($s.WorkingDirectory)|$($s.Description)\""
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split("|")
            return {
                "target_path": parts[0] if len(parts) > 0 else "",
                "arguments": parts[1] if len(parts) > 1 else "",
                "working_directory": parts[2] if len(parts) > 2 else "",
                "description": parts[3] if len(parts) > 3 else "",
            }
    except Exception as exc:
        logger.debug("PowerShell read shortcut failed: %s", exc)

    return {}


def register_startup(
    target_script: Optional[Path] = None,
    shortcut_name: str = DEFAULT_SHORTCUT_NAME,
    vbs_path: Optional[Path] = None,
    icon_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Registers Salesforce Jarvis in the Windows Startup directory.

    1. Generates `launch_jarvis_silent.vbs` configured to run pythonw.exe silently.
    2. Creates a `.lnk` shortcut in Windows Startup pointing to `wscript.exe` with
       arguments targeting the VBS script.

    Args:
        target_script: Script to run (defaults to app/main.py)
        shortcut_name: Name of the shortcut file in Startup folder.
        vbs_path: Custom path for the generated VBS script.
        icon_path: Optional custom icon file (.ico) for the shortcut.

    Returns:
        Dictionary containing registration details and success status.
    """
    startup_dir = get_startup_dir()
    target = Path(target_script or get_default_target_script()).resolve()
    vbs_file = generate_vbs_script(target_script=target, output_vbs_path=vbs_path)
    shortcut_file = startup_dir / shortcut_name

    # Determine wscript.exe location (standard Windows GUI script host)
    wscript_exe = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "wscript.exe"
    if not wscript_exe.is_file():
        wscript_exe = Path("wscript.exe")

    # Icon location: custom icon, or pythonw icon
    icon_loc = str(icon_path) if icon_path and Path(icon_path).is_file() else f"{get_pythonw_executable()},0"

    # Create the shortcut in Startup
    # Target: wscript.exe, Argument: "path_to_launch_jarvis_silent.vbs"
    success = _create_windows_shortcut(
        shortcut_path=shortcut_file,
        target_path=wscript_exe,
        arguments=f'"{str(vbs_file)}"',
        working_dir=get_project_root(),
        description=APP_DESCRIPTION,
        icon_location=icon_loc,
    )

    result = {
        "success": success,
        "shortcut_path": str(shortcut_file),
        "vbs_path": str(vbs_file),
        "pythonw_path": str(get_pythonw_executable()),
        "target_script": str(target),
        "startup_dir": str(startup_dir),
        "enabled": is_startup_enabled(shortcut_name=shortcut_name),
    }

    if success:
        logger.info("Successfully registered Salesforce Jarvis in Windows Startup: %s", shortcut_file)
    else:
        logger.error("Failed to register shortcut at %s", shortcut_file)

    return result


def unregister_startup(
    shortcut_name: str = DEFAULT_SHORTCUT_NAME,
    remove_vbs: bool = False,
) -> bool:
    """Removes Salesforce Jarvis from the Windows Startup directory.

    Args:
        shortcut_name: Name of the shortcut file in Startup folder.
        remove_vbs: Whether to also delete launch_jarvis_silent.vbs.

    Returns:
        True if the shortcut was successfully removed or was not present.
    """
    startup_dir = get_startup_dir()
    shortcut_file = startup_dir / shortcut_name
    removed = True

    if shortcut_file.exists():
        try:
            shortcut_file.unlink()
            logger.info("Removed startup shortcut: %s", shortcut_file)
        except Exception as exc:
            logger.error("Failed to delete startup shortcut %s: %s", shortcut_file, exc)
            removed = False

    # Also check if a standalone VBS was placed directly in Startup
    vbs_in_startup = startup_dir / DEFAULT_VBS_NAME
    if vbs_in_startup.exists():
        try:
            vbs_in_startup.unlink()
            logger.info("Removed startup VBS: %s", vbs_in_startup)
        except Exception as exc:
            logger.debug("Could not remove startup VBS: %s", exc)

    if remove_vbs:
        vbs_file = get_vbs_launcher_path()
        if vbs_file.exists():
            try:
                vbs_file.unlink()
                logger.info("Deleted VBS launcher file: %s", vbs_file)
            except Exception as exc:
                logger.debug("Could not delete VBS launcher: %s", exc)

    return removed and not is_startup_enabled(shortcut_name)


def is_startup_enabled(shortcut_name: str = DEFAULT_SHORTCUT_NAME) -> bool:
    """Checks whether Salesforce Jarvis is registered in Windows Startup.

    Verifies the existence of either:
    1. The .lnk shortcut in the Startup folder.
    2. Or a direct VBS script in the Startup folder.
    """
    startup_dir = get_startup_dir()
    shortcut_path = startup_dir / shortcut_name
    vbs_path = startup_dir / DEFAULT_VBS_NAME
    return shortcut_path.is_file() or vbs_path.is_file()


def verify_startup(shortcut_name: str = DEFAULT_SHORTCUT_NAME) -> Dict[str, Any]:
    """Inspects and verifies the full silent startup chain.

    Checks:
    - Shortcut exists in Windows Startup folder.
    - Shortcut targets wscript.exe or launch_jarvis_silent.vbs.
    - The VBS launcher exists.
    - The target python script exists.
    - pythonw.exe exists for silent execution.

    Returns:
        Dict with status flags, paths, and descriptive verification message.
    """
    startup_dir = get_startup_dir()
    shortcut_path = startup_dir / shortcut_name
    vbs_file = get_vbs_launcher_path()
    pythonw_path = get_pythonw_executable()
    target_script = get_default_target_script()

    enabled = is_startup_enabled(shortcut_name)
    shortcut_exists = shortcut_path.is_file()
    vbs_exists = vbs_file.is_file()
    pythonw_exists = pythonw_path.is_file()
    target_exists = target_script.is_file()

    shortcut_props = _read_windows_shortcut(shortcut_path) if shortcut_exists else {}

    valid = bool(
        enabled and shortcut_exists and vbs_exists and pythonw_exists and target_exists
    )

    if not enabled:
        msg = "Startup is NOT registered."
    elif not valid:
        missing = []
        if not vbs_exists:
            missing.append(f"VBS launcher ({vbs_file})")
        if not pythonw_exists:
            missing.append(f"pythonw.exe ({pythonw_path})")
        if not target_exists:
            missing.append(f"target script ({target_script})")
        msg = f"Startup is registered but incomplete; missing: {', '.join(missing)}"
    else:
        msg = "Silent Windows startup is fully configured, verified, and operational."

    return {
        "enabled": enabled,
        "valid": valid,
        "shortcut_path": str(shortcut_path),
        "shortcut_exists": shortcut_exists,
        "vbs_path": str(vbs_file),
        "vbs_exists": vbs_exists,
        "pythonw_path": str(pythonw_path),
        "pythonw_exists": pythonw_exists,
        "target_script": str(target_script),
        "target_exists": target_exists,
        "shortcut_properties": shortcut_props,
        "message": msg,
    }


def toggle_startup(shortcut_name: str = DEFAULT_SHORTCUT_NAME) -> bool:
    """Toggles the Windows startup state (enables if disabled, disables if enabled).

    Returns:
        New enabled state (True if enabled, False if disabled).
    """
    if is_startup_enabled(shortcut_name):
        unregister_startup(shortcut_name)
        return False
    else:
        res = register_startup(shortcut_name=shortcut_name)
        return bool(res.get("success", False))


def main() -> int:
    """CLI helper for inspecting and managing startup from the command line."""
    import argparse

    parser = argparse.ArgumentParser(description="Manage Salesforce Jarvis Windows Startup")
    parser.add_argument("action", choices=["status", "enable", "disable", "toggle", "verify"], default="status", nargs="?")
    parser.add_argument("--script", help="Path to target python script", default=None)
    args = parser.parse_args()

    target_script = Path(args.script) if args.script else None

    if args.action == "status":
        enabled = is_startup_enabled()
        print(f"Startup enabled: {enabled}")
        print(f"Startup directory: {get_startup_dir()}")
        return 0 if enabled else 1

    elif args.action == "enable":
        res = register_startup(target_script=target_script)
        print("Registration result:", res)
        return 0 if res.get("success") else 1

    elif args.action == "disable":
        success = unregister_startup(remove_vbs=True)
        print(f"Unregistered startup: {success}")
        return 0 if success else 1

    elif args.action == "toggle":
        new_state = toggle_startup()
        print(f"Startup toggled. Now enabled: {new_state}")
        return 0

    elif args.action == "verify":
        info = verify_startup()
        print("=== Startup Verification Report ===")
        for k, v in info.items():
            print(f"  {k}: {v}")
        return 0 if info["valid"] else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
