"""Tiny per-user settings store for the GUI (calibration, etc.).

The file lives under APPDATA on Windows and ~/.config elsewhere. Read/write
failures are non-fatal: the app simply falls back to defaults.
"""
import json
import os

APP_NAME = "DataMatrixVerifier"
ENV_OVERRIDE = "DM_VERIFIER_CONFIG"


def config_path():
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME, "settings.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME, "settings.json")


def load_settings():
    """Return the saved settings dict, or {} if none/invalid."""
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(settings):
    """Atomically write settings; returns True on success."""
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False
