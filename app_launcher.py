"""
app_launcher.py — ARJUN App Launcher
Launches installed desktop apps and opens browser services locally.
"""

import logging
import os
import re
import shutil
import subprocess
import webbrowser
from difflib import get_close_matches

from config import APP_REGISTRY

logger = logging.getLogger(__name__)

USERNAME = os.environ.get("USERNAME", "user")

_CHROME_NAMES = {
    "chrome",
    "google chrome",
}
_WEB_APPS = {
    "spotify": "https://open.spotify.com/",
    "spotify music": "https://open.spotify.com/",
    "youtube": "https://www.youtube.com/",
    "you tube": "https://www.youtube.com/",
    "youtube music": "https://music.youtube.com/",
}


def _resolve_path(raw: str) -> str:
    """Replace the {USERNAME} placeholder in configured app paths."""
    return raw.replace("{USERNAME}", USERNAME)


def _normalize_request(name: str) -> str:
    name = re.sub(r"\s+", " ", name.lower().strip())
    name = re.sub(r"^(?:(?:please|can you|could you)\s+)?(?:open|launch|start|run)\s+", "", name)
    name = re.sub(r"\s+(?:in|with|using)\s+(?:google\s+)?chrome$", "", name)
    name = re.sub(r"\s+(?:app|application|website|site|browser)$", "", name)
    return name.strip()


def _find_chrome_executable() -> str:
    """Find Chrome using PATH, Windows App Paths, or standard install locations."""
    for command in ("chrome.exe", "chrome"):
        executable = shutil.which(command)
        if executable and os.path.isfile(executable):
            return executable

    if os.name == "nt":
        try:
            import winreg
        except ImportError:
            winreg = None

        if winreg is not None:
            app_path_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
            access_modes = (
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
                winreg.KEY_READ,
            )
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for access in access_modes:
                    try:
                        with winreg.OpenKey(hive, app_path_key, 0, access) as key:
                            executable, _ = winreg.QueryValueEx(key, None)
                    except OSError:
                        continue
                    executable = os.path.expandvars(executable.strip('"'))
                    if os.path.isfile(executable):
                        return executable

    roots = (
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
    )
    for root in roots:
        if not root:
            continue
        executable = os.path.join(root, "Google", "Chrome", "Application", "chrome.exe")
        if os.path.isfile(executable):
            return executable
    return ""


def _open_in_chrome(url: str = "") -> str:
    """Open a URL or blank tab in Chrome, falling back to the default browser."""
    executable = _find_chrome_executable()
    if executable:
        command = [executable]
        if url:
            command.append(url)
        try:
            subprocess.Popen(
                command,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return "chrome"
        except OSError:
            logger.exception("Could not start Chrome at %s; trying the default browser.", executable)

    if not webbrowser.open(url or "about:blank", new=2):
        raise RuntimeError("Chrome and a default browser could not be opened.")
    return "default"


def _fuzzy_match(name: str) -> str:
    """Find the closest configured desktop app name."""
    name_lower = _normalize_request(name)
    if name_lower in APP_REGISTRY:
        return name_lower

    matches = get_close_matches(name_lower, APP_REGISTRY.keys(), n=1, cutoff=0.6)
    if matches:
        return matches[0]

    for key in APP_REGISTRY:
        if name_lower in key or key in name_lower:
            return key
    return ""


def launch_app(name: str) -> str:
    """Open a desktop application or a browser-based service by name."""
    if not isinstance(name, str) or not name.strip():
        return "Tell me which application or website you want to open."

    requested = _normalize_request(name)
    if requested in _CHROME_NAMES:
        try:
            browser = _open_in_chrome()
        except Exception as exc:
            logger.exception("Could not open Chrome.")
            return f"Failed to open Chrome: {exc}"
        if browser == "chrome":
            return "Opening Chrome for you."
        return "Chrome was not found; I opened your default browser instead."

    if requested in _WEB_APPS:
        service = "YouTube" if "youtube" in requested or requested == "you tube" else "Spotify"
        try:
            browser = _open_in_chrome(_WEB_APPS[requested])
        except Exception as exc:
            logger.exception("Could not open %s in a browser.", service)
            return f"Failed to open {service}: {exc}"
        if browser == "chrome":
            return f"Opening {service} in Chrome."
        return f"Chrome was not found; opening {service} in your default browser."

    matched = _fuzzy_match(requested)
    if not matched:
        return f"I don't have {name} in my app list. You can add it to APP_REGISTRY in config.py."

    cmd = _resolve_path(APP_REGISTRY[matched])
    display_name = matched.title()
    try:
        if cmd.startswith("ms-"):
            os.startfile(cmd)
        elif " --" in cmd:
            parts = cmd.split(" ", 1)
            subprocess.Popen(parts, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            subprocess.Popen(
                cmd,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                shell=True,
            )
        logger.info("Launched: %s (%s)", display_name, cmd)
        return f"Opening {display_name} for you."
    except FileNotFoundError:
        return f"Could not find {display_name}. It may not be installed."
    except Exception as exc:
        logger.exception("Launch error for %s.", name)
        return f"Failed to open {display_name}: {exc}"


def list_available_apps() -> str:
    """Return a natural-language list of desktop apps and web services."""
    names = sorted(set(APP_REGISTRY) | {"chrome", "spotify", "youtube"})
    return "Apps I can open for you: " + ", ".join(names)
