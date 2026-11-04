"""The work itself: bake a URL into a Chromium PWA, remove one, list them.

Baking runs the bundled install-pwa-full.sh (session 557's full-fidelity installer). The
installer writes a row into Chromium's sync LevelDB, which Chromium locks while it runs, so a
bake first closes any open Chromium web apps and Chromium itself, waits until the lock is
really free, bakes, and reopens what it closed (session 585's findings 3 and 4).
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from . import config
from .validate import RequestError, resolve_app_path

ProgressFn = Callable[[str], None]

_IMAGE_MAGIC = (
    b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"\x00\x00\x01\x00", b"BM", b"II*\x00", b"MM\x00*", b"icns",
)
MAX_ICON_BYTES = 5 * 1024 * 1024


def sub_env() -> dict[str, str]:
    """The environment for every subprocess: Homebrew on PATH even when launched from the app."""
    env = dict(os.environ)
    parts = [p for p in env.get("PATH", "").split(":") if p]
    for extra in ("/usr/sbin", "/usr/bin", "/bin", "/sbin", "/usr/local/bin", "/opt/homebrew/sbin", "/opt/homebrew/bin"):
        if extra not in parts:
            parts.insert(0, extra)
    env["PATH"] = ":".join(parts)
    env["PWA_BAKER_CHROMIUM_USER_DATA"] = str(config.CHROMIUM_USER_DATA)
    env["PWA_BAKER_APPS_DIR"] = str(config.APPS_DIR)
    return env


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd, path=sub_env()["PATH"])


def _run(cmd: list[str], timeout: float = 30, **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=sub_env(), **kwargs)


# --- Chromium: who is running, and is the database free -----------------------------------


def _ps() -> list[tuple[int, str]]:
    try:
        out = _run(["ps", "-axo", "pid=,command="], timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        line = line.strip()
        pid, _, command = line.partition(" ")
        if pid.isdigit():
            rows.append((int(pid), command.strip()))
    return rows


def running_shims(apps_dir: Path = None) -> dict[str, list[int]]:
    """Open Chromium web apps, as {app path: [pids]}. Shims are named after their app, not Chromium."""
    apps_dir = apps_dir or config.APPS_DIR
    marker = str(apps_dir).rstrip("/") + "/"
    found: dict[str, list[int]] = {}
    for pid, command in _ps():
        if marker not in command:
            continue
        name = command.split(marker, 1)[1].split(".app", 1)[0]
        path = apps_dir / (name + ".app")
        if name and path.is_dir():
            found.setdefault(str(path), []).append(pid)
    return found


def chromium_pids() -> list[int]:
    exe = str(config.CHROMIUM_APP / "Contents" / "MacOS") + "/"
    return [pid for pid, command in _ps() if command.startswith(exe)]


_NODE_PROBE = r"""
const {ClassicLevel}=require('classic-level');
const db=new ClassicLevel(process.argv[2]);
(async()=>{ if(db.status!=='open')await db.open(); await db.close(); process.exit(0);})()
 .catch(()=>process.exit(1));
"""


def lock_free() -> bool:
    """Ground truth: can the sync LevelDB actually be opened right now?"""
    db = config.CHROMIUM_USER_DATA / "-" / "Sync Data" / "LevelDB"
    if not db.exists():
        return True
    node = which("node")
    modules = config.NODE_CACHE / "node_modules"
    if node and (modules / "classic-level").is_dir():
        env = dict(sub_env(), NODE_PATH=str(modules))
        try:
            r = subprocess.run([node, "-", str(db)], input=_NODE_PROBE, capture_output=True, text=True, env=env, timeout=15)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    lock = db / "LOCK"
    if not lock.exists():
        return True
    import fcntl

    try:
        with open(lock, "a") as handle:
            fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.lockf(handle, fcntl.LOCK_UN)
        return True
    except OSError:
        return False


def _signal(pids: list[int], sig: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def close_chromium(shims: dict[str, list[int]], progress: ProgressFn, timeout: float = 20) -> bool:
    """Close the given web apps and Chromium, gracefully first; True once the database is free."""
    _signal([pid for pids in shims.values() for pid in pids], signal.SIGTERM)
    time.sleep(0.5)
    _signal(chromium_pids(), signal.SIGTERM)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not chromium_pids() and lock_free():
            return True
        # A shim can bring Chromium back after it quits; keep asking until it stays down.
        _signal([pid for pids in running_shims().values() for pid in pids], signal.SIGTERM)
        _signal(chromium_pids(), signal.SIGTERM)
        time.sleep(0.5)
    progress("Chromium did not quit in time; forcing it closed")
    _signal([pid for pids in running_shims().values() for pid in pids], signal.SIGKILL)
    _signal(chromium_pids(), signal.SIGKILL)
    time.sleep(1)
    # A forced kill leaves singleton files behind that break the next launch (557 pitfall 11).
    for leftover in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        path = config.CHROMIUM_USER_DATA / leftover
        if path.is_symlink() or path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    return lock_free()


def profile_ready() -> bool:
    """Has Chromium ever used its "-" profile, the one app shims open?

    On a profile Chromium has never opened, a baked app opens as a plain browser tab instead
    of its own window (seen on a fresh Mac, PWA Baker CI 2026-11-04).
    """
    try:
        with open(config.CHROMIUM_USER_DATA / "Local State") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return False
    return "-" in state.get("profile", {}).get("info_cache", {})


def prepare_profile(progress: ProgressFn, timeout: float = 30) -> bool:
    """Open Chromium once on the "-" profile, then close it, so that profile exists."""
    progress("Setting up Chromium for web apps (first bake only)")
    _run(["open", "-na", str(config.CHROMIUM_APP), "--args", "--profile-directory=-", "--no-first-run",
          "--no-default-browser-check", "about:blank"], timeout=30)
    deadline = time.time() + timeout
    while time.time() < deadline and not profile_ready():
        time.sleep(1)
    time.sleep(2)  # let it finish writing the profile before it is asked to quit
    _signal(chromium_pids(), signal.SIGTERM)
    while time.time() < deadline + 15 and chromium_pids():
        time.sleep(0.5)
    return profile_ready()


# --- icons ---------------------------------------------------------------------------------


def fetch_icon(url: str, workdir: Path) -> tuple[Optional[str], Optional[str]]:
    """Download an icon the request named; returns (local path, note when it could not be used)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PWA-Baker"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(MAX_ICON_BYTES + 1)
    except Exception as exc:  # noqa: BLE001 - any fetch failure just means "no icon from there"
        return None, "Could not download the icon (%s); used the site's own icon instead." % exc.__class__.__name__
    if len(data) > MAX_ICON_BYTES:
        return None, "The icon was over 5 MB; used the site's own icon instead."
    if not data.startswith(_IMAGE_MAGIC) and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        hint = " (it looked like a web page, so it probably needs a sign-in)" if data.lstrip()[:1] == b"<" else ""
        return None, "The icon address did not give a picture%s; used the site's own icon instead." % hint
    path = workdir / "requested-icon"
    path.write_bytes(data)
    return str(path), None


# --- bake / uninstall / list ---------------------------------------------------------------


def _parse_installer_output(out: str) -> dict[str, str]:
    fields = {}
    for line in out.splitlines():
        for key, label in (("app_path", "Created:"), ("app_id", "App id:"), ("name", "name:"),
                           ("icon_source", "icon_source:"), ("start_url", "start_url:"), ("manifest", "manifest:")):
            if line.startswith(label):
                fields[key] = line[len(label):].strip()
    return fields


def bake(url: str, name: Optional[str], icon: Optional[str], cfg: "config.Config", progress: ProgressFn) -> dict[str, Any]:
    installer = config.INSTALLER
    if not installer.is_file():
        raise RequestError("installer_missing", "The bundled installer is missing: %s" % installer)
    if not config.CHROMIUM_APP.is_dir():
        raise RequestError("chromium_missing", "Chromium is not installed at %s." % config.CHROMIUM_APP)

    result: dict[str, Any] = {}
    if not profile_ready() and not chromium_pids():
        if not prepare_profile(progress):
            raise RequestError("profile_not_ready", "Chromium did not set up its app profile; open Chromium once, quit it, and try again.")
        result["prepared_profile"] = True
    shims = running_shims()
    closed: list[str] = []
    reopen_chromium = False
    if shims or not lock_free():
        if not cfg.get("close_open_apps"):
            raise RequestError(
                "chromium_running",
                "Chromium is open (%s). Close it and try again, or turn on \"close open web apps\" in PWA Baker."
                % (", ".join(Path(p).stem for p in shims) or "Chromium"),
            )
        progress("Closing open web apps for a moment: %s" % (", ".join(Path(p).stem for p in shims) or "Chromium"))
        closed = sorted(shims)
        reopen_chromium = not shims and bool(chromium_pids())
        if not close_chromium(shims, progress):
            raise RequestError("chromium_locked", "Chromium would not let go of its app list; quit Chromium and try again.")
        result["closed_apps"] = [Path(p).stem for p in closed] or ["Chromium"]

    with tempfile.TemporaryDirectory(prefix="pwa-baker-") as work:
        workdir = Path(work)
        icon_path = None
        if icon and icon.startswith(("http://", "https://")):
            progress("Downloading the icon")
            icon_path, note = fetch_icon(icon, workdir)
            if note:
                result["icon_note"] = note
        elif icon:
            icon_path = icon
        cmd = ["/bin/bash", str(installer), url, "--browser-app", str(config.CHROMIUM_APP)]
        if name:
            cmd += ["--name", name]
        if icon_path:
            cmd += ["--icon", icon_path]
        if closed and not lock_free():
            raise RequestError("chromium_relocked", "Chromium reopened before the bake could start; try again.")
        progress("Baking")
        started = time.time()
        try:
            proc = _run(cmd, timeout=300)
        except subprocess.TimeoutExpired:
            raise RequestError("installer_timeout", "The installer took more than 5 minutes and was stopped.")
    out = (proc.stdout or "") + (proc.stderr or "")
    fields = _parse_installer_output(out)
    result.update(fields)
    result["seconds"] = round(time.time() - started, 1)
    result["log_tail"] = out[-2000:]
    if reopen_chromium:
        closed = closed + [str(config.CHROMIUM_APP)]
    if proc.returncode != 0 or "app_path" not in fields:
        _reopen(closed)
        err = RequestError("installer_failed", "The installer failed (exit %s): %s" % (proc.returncode, _last_line(out)))
        err.details = result  # type: ignore[attr-defined]
        raise err

    app_path = Path(fields["app_path"])
    result["extras"] = _finish_install(app_path, cfg, progress)
    result["reopened_apps"] = [Path(p).stem for p in _reopen(closed)]
    return result


def _last_line(out: str) -> str:
    lines = [line for line in out.strip().splitlines() if line.strip()]
    return lines[-1][:300] if lines else "no output"


def _reopen(paths: list[str]) -> list[str]:
    reopened = []
    for path in paths:
        if os.path.isdir(path):
            try:
                _run(["open", path], timeout=15)
                reopened.append(path)
            except (OSError, subprocess.SubprocessError):
                pass
    return reopened


def _finish_install(app_path: Path, cfg: "config.Config", progress: ProgressFn) -> list[str]:
    extras = []
    if cfg.get("add_to_dock"):
        dockutil = which("dockutil")
        if dockutil:
            progress("Adding it to the Dock")
            found = _run([dockutil, "--find", app_path.stem], timeout=15).returncode == 0
            if not found:
                r = _run([dockutil, "--add", str(app_path), "--no-restart"], timeout=15)
                extras.append("dock:added" if r.returncode == 0 else "dock:failed")
            else:
                extras.append("dock:already")
            _run(["killall", "Dock"], timeout=10)
        else:
            extras.append("dock:skipped (dockutil not installed)")
    if cfg.get("desktop_alias"):
        link = config.DESKTOP_DIR / app_path.name
        if not link.exists() and not link.is_symlink():
            try:
                link.symlink_to(app_path)
                extras.append("desktop:added")
            except OSError as exc:
                extras.append("desktop:failed (%s)" % exc.__class__.__name__)
        else:
            extras.append("desktop:already")
    return extras


def read_app(path: Path) -> Optional[dict[str, Any]]:
    """What a baked app's Info.plist says, or None for anything that is not a Chromium web app."""
    try:
        with open(path / "Contents" / "Info.plist", "rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    if "CrAppModeShortcutID" not in info:
        return None
    return {
        "name": path.stem,
        "path": str(path),
        "app_id": info.get("CrAppModeShortcutID"),
        "url": info.get("CrAppModeShortcutURL"),
        "modified": int(path.stat().st_mtime),
    }


def list_apps() -> list[dict[str, Any]]:
    apps = []
    open_now = running_shims()
    if config.APPS_DIR.is_dir():
        for path in sorted(config.APPS_DIR.glob("*.app"), key=lambda p: p.name.lower()):
            info = read_app(path)
            if info:
                info["running"] = str(path) in open_now
                apps.append(info)
    return apps


def uninstall(name: str, progress: ProgressFn) -> dict[str, Any]:
    path = resolve_app_path(config.APPS_DIR, name)
    if not path.is_dir():
        raise RequestError("not_found", "There is no baked app called %s." % name)
    if read_app(path) is None:
        raise RequestError("not_a_web_app", "%s is not a Chromium web app, so PWA Baker leaves it alone." % name)
    removed = []
    pids = running_shims().get(str(path), [])
    if pids:
        progress("Closing %s" % path.stem)
        _signal(pids, signal.SIGTERM)
        time.sleep(1)
    shutil.rmtree(path)
    removed.append(str(path))
    desk = config.DESKTOP_DIR / path.name
    if desk.is_symlink() and os.path.realpath(os.readlink(desk)) == os.path.realpath(path):
        desk.unlink()
        removed.append(str(desk))
    elif desk.is_file() and desk.stat().st_size < 1024 * 1024:  # a Finder alias from the old daemon
        desk.unlink()
        removed.append(str(desk))
    dockutil = which("dockutil")
    if dockutil and _run([dockutil, "--find", path.stem], timeout=15).returncode == 0:
        _run([dockutil, "--remove", path.stem, "--no-restart"], timeout=15)
        _run(["killall", "Dock"], timeout=10)
        removed.append("dock entry")
    # Chromium's own record of the app stays (harmless; a later bake of the same site reuses it).
    return {"removed": removed}
