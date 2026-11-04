"""The setup checklist the app shows: what baking needs on this Mac, and how to fix each gap."""

from __future__ import annotations

import plistlib
import sys
from typing import Any

from . import config
from .baker import which


def _check(check_id: str, label: str, ok: bool, detail: str, fix: str = "", required: bool = True) -> dict[str, Any]:
    return {"id": check_id, "label": label, "ok": ok, "detail": detail, "fix": "" if ok else fix, "required": required}


def run_checks() -> list[dict[str, Any]]:
    checks = []

    app = config.CHROMIUM_APP
    version = ""
    try:
        with open(app / "Contents" / "Info.plist", "rb") as handle:
            version = plistlib.load(handle).get("CFBundleShortVersionString", "")
    except (OSError, plistlib.InvalidFileException, ValueError):
        pass
    checks.append(_check(
        "chromium", "Chromium", app.is_dir(),
        ("Chromium %s at %s" % (version, app)) if app.is_dir() else "Not found at %s" % app,
        "Download the Apple-silicon snapshot from commondatastorage.googleapis.com/chromium-browser-snapshots "
        "(folder Mac_Arm), move Chromium.app to /Applications, then run: xattr -dr com.apple.quarantine /Applications/Chromium.app",
    ))

    if app.is_dir():
        from .baker import profile_ready
        ready = profile_ready()
        checks.append(_check(
            "profile", "Chromium app profile", True,
            "Set up" if ready else "Not used yet; PWA Baker sets it up on the first bake (Chromium opens for a moment)",
            required=False,
        ))

    node, npm = which("node"), which("npm")
    checks.append(_check(
        "node", "Node.js", bool(node and npm),
        node or "node and npm not found", "Install it with: brew install node",
    ))

    checks.append(_check(
        "template", "Chromium app template", config.TEMPLATE.is_file(),
        "Bundled" if config.TEMPLATE.is_file() else "Missing from the app", "Reinstall PWA Baker.",
    ))

    for tool in ("sips", "iconutil", "codesign", "curl"):
        path = which(tool)
        checks.append(_check(
            tool, tool, bool(path), path or "not found",
            "Install the Xcode command line tools: xcode-select --install",
        ))

    dockutil = which("dockutil")
    checks.append(_check(
        "dockutil", "Dock pinning (optional)", bool(dockutil), dockutil or "dockutil not installed",
        "Install it with: brew install dockutil", required=False,
    ))

    checks.append(_check(
        "python", "Python", sys.version_info >= (3, 9),
        "%s (%d.%d)" % (sys.executable, sys.version_info[0], sys.version_info[1]), "Install python 3.9 or newer.",
    ))
    return checks


def ready(checks: list[dict[str, Any]]) -> bool:
    return all(c["ok"] for c in checks if c["required"])
