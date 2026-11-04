"""Where the engine keeps things, and its settings file.

Settings live in ~/.config/pwa-baker/config.json, the file the old pwa-bakerd daemon used, so
its bearer token carries over. Every path can be moved with an environment variable, which
is how the tests run the engine in a temporary directory.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any

HOME = Path.home()


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


CONFIG_FILE = _env_path("PWA_BAKER_CONFIG", HOME / ".config" / "pwa-baker" / "config.json")
LOG_DIR = _env_path("PWA_BAKER_LOG_DIR", HOME / "Library" / "Logs" / "pwa-baker")
STATE_DIR = _env_path("PWA_BAKER_STATE_DIR", HOME / "Library" / "Application Support" / "PWA Baker")
APPS_DIR = _env_path("PWA_BAKER_APPS_DIR", HOME / "Applications" / "Chromium Apps.localized")
CHROMIUM_USER_DATA = _env_path(
    "PWA_BAKER_CHROMIUM_USER_DATA", HOME / "Library" / "Application Support" / "Chromium"
)
CHROMIUM_APP = _env_path("PWA_BAKER_CHROMIUM_APP", Path("/Applications/Chromium.app"))
DESKTOP_DIR = _env_path("PWA_BAKER_DESKTOP_DIR", HOME / "Desktop")
RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
INSTALLER = _env_path("PWA_BAKER_INSTALLER", RESOURCES_DIR / "install-pwa-full.sh")
TEMPLATE = RESOURCES_DIR / "calib" / "webapp_record_template.bin"
NODE_CACHE = HOME / ".cache" / "install-pwa-full-node"

DEFAULT_PORT = 7247

DEFAULTS: dict[str, Any] = {
    "port": DEFAULT_PORT,
    "dropbox_dir": str(HOME / "PWA Baker"),
    "dropbox_enabled": True,
    "add_to_dock": True,
    "desktop_alias": True,
    # When Chromium apps are open during a bake: close them, bake, and reopen them. When
    # false the bake fails with "chromium_running" instead.
    "close_open_apps": True,
}

# Keys the old pwa-bakerd daemon wrote, mapped to their new names.
_LEGACY_KEYS = {"allow_dock": "add_to_dock", "allow_desktop_alias": "desktop_alias"}


class Config:
    """The settings file, read once and written back on every change."""

    def __init__(self, path: Path = CONFIG_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        data: dict[str, Any] = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
            except ValueError:
                data = {}
        for old, new in _LEGACY_KEYS.items():
            if old in data and new not in data:
                data[new] = data[old]
        changed = False
        if not data.get("token"):
            data["token"] = secrets.token_urlsafe(32)
            changed = True
        for key, value in DEFAULTS.items():
            if key not in data:
                data[key] = value
                changed = True
        self.data = data
        if changed or not self.path.exists():
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def get(self, key: str) -> Any:
        return self.data.get(key, DEFAULTS.get(key))

    @property
    def token(self) -> str:
        return str(self.data["token"])

    @property
    def dropbox_dir(self) -> Path:
        return Path(str(self.get("dropbox_dir"))).expanduser()

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Apply the settings the app may change; returns the public settings."""
        allowed = {"dropbox_enabled", "add_to_dock", "desktop_alias", "close_open_apps"}
        with self._lock:
            for key, value in changes.items():
                if key in allowed and isinstance(value, bool):
                    self.data[key] = value
            self.save()
        return self.public_settings()

    def public_settings(self) -> dict[str, Any]:
        keys = ("port", "dropbox_dir", "dropbox_enabled", "add_to_dock", "desktop_alias", "close_open_apps")
        return {key: self.get(key) for key in keys}
