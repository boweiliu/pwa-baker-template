#!/usr/bin/env python3
"""Ask the PWA Baker app on the user's Mac for web apps, through its shared folder.

    bake_pwa_on_mac.py status
    bake_pwa_on_mac.py bake <url> [--name NAME] [--icon FILE_OR_URL] [--wait SECONDS]
    bake_pwa_on_mac.py uninstall <name> [--wait SECONDS]
    bake_pwa_on_mac.py result <request id>

The Mac app watches ~/PWA Baker/ (requests/, results/, icons/, status.json; its README.md has
the protocol). This script reaches that folder one of two ways, best first:

1. the synced copy Studio keeps at ~/synced_folders/<device>/<path> once the user approved
   write access with syncing on: plain file writes, and it keeps working while the Mac sleeps
   (requests wait and run when it wakes);
2. Studio's file server (WebDAV through the latchkey gateway) when there is a grant but no
   synced copy: needs the Mac awake with Studio open.

Every command prints one JSON object. With no access yet it prints "channel": "none" and the
permission request to send (see the SKILL.md for how).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

FOLDER_NAME = "PWA Baker"
PROXY = "http://latchkey-self.invalid"
SYNCED_ROOT = Path.home() / "synced_folders"
STALE_SECONDS = 300
INSTALL_LINE = (
    "git clone --depth 1 --filter=blob:none --sparse https://github.com/boweiliu/pwa-baker-template ~/code/pwa-baker-src && cd ~/code/pwa-baker-src && git sparse-checkout set mac-apps/pwa-baker && mac-apps/pwa-baker/install.sh"
)


def latchkey(args: list[str], device: str | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    cmd = ["latchkey", "curl", "-s"]
    if device:
        cmd += ["-H", "X-Latchkey-Device: " + device]
    return subprocess.run(cmd + args, capture_output=True, timeout=timeout)


def devices() -> list[dict[str, Any]]:
    r = latchkey([PROXY + "/devices"])
    try:
        return json.loads(r.stdout).get("devices", [])
    except ValueError:
        return []


def pick_device(wanted: str | None) -> dict[str, Any] | None:
    found = devices()
    if wanted:
        return next((d for d in found if wanted in (d["device_id"], d.get("hostname"))), None)
    macs = [d for d in found if "mac" in (d.get("hostname") or "").lower()]
    return (macs or found or [None])[0]


def granted_paths(device: str) -> dict[str, str]:
    """{path: "read"|"write"} of this agent's file grants on the device."""
    r = latchkey([PROXY + "/permissions/self"], device=device)
    try:
        rules = json.loads(r.stdout).get("rules", [])
    except ValueError:
        return {}
    paths: dict[str, str] = {}
    for rule in rules:
        for perms in rule.values():
            for perm in perms:
                m = re.match(r"minds-file-server-(read|write)-(?:([\w-]+):)?(/.*)$", perm)
                if m and (m.group(2) in (None, device)):
                    path = m.group(3).rstrip("/")
                    if m.group(1) == "write" or path not in paths:
                        paths[path] = m.group(1)
    return paths


class Folder:
    """The Mac's PWA Baker folder, through whichever channel is available."""

    def __init__(self, device: str, mac_path: str, local: Path | None, access: str) -> None:
        self.device = device
        self.mac_path = mac_path
        self.local = local
        self.access = access

    @property
    def channel(self) -> str:
        return "synced" if self.local else "file-server"

    def url(self, rel: str) -> str:
        quoted = urllib.parse.quote(self.mac_path + "/" + rel)
        return "%s/minds-api-proxy/api/v1/files/%s%s" % (PROXY, self.device, quoted)

    def read(self, rel: str) -> str | None:
        if self.local:
            path = self.local / rel
            return path.read_text() if path.exists() else None
        r = latchkey(["-f", self.url(rel)], device=self.device)
        return r.stdout.decode() if r.returncode == 0 else None

    def write(self, rel: str, data: bytes) -> None:
        if self.local:
            target = self.local / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name("." + target.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            return
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(data)
        try:
            r = latchkey(["-f", "-T", handle.name, self.url(rel)], device=self.device, timeout=120)
            if r.returncode != 0:
                raise SystemExit(emit({"ok": False, "error": "write_failed", "channel": self.channel,
                                       "message": "Could not write %s on the Mac (curl exit %d): %s"
                                       % (rel, r.returncode, r.stdout.decode()[:300])}))
        finally:
            os.unlink(handle.name)


def find_folder(device_arg: str | None) -> tuple[Folder | None, dict[str, Any]]:
    dev = pick_device(device_arg)
    if not dev:
        return None, {"ok": False, "channel": "none", "error": "no_device",
                      "message": "No computer is connected to Studio."}
    device = dev["device_id"]
    info = {"device": device, "hostname": dev.get("hostname"), "device_last_seen": dev.get("last_seen_at")}
    # 1. a synced copy
    synced = SYNCED_ROOT / device
    if synced.is_dir():
        # ~/PWA Baker on the Mac is /Users/<user>/PWA Baker there.
        # An empty copy means the sync has not delivered (or failed: Studio cannot sync some
        # host providers); use the file server then.
        for path in sorted(synced.glob("*/*/" + FOLDER_NAME)):
            if (path / "README.md").exists() or (path / "status.json").exists():
                mac_path = "/" + str(path.relative_to(synced))
                access = granted_paths(device).get(mac_path, "write")
                return Folder(device, mac_path, path, access), info
    # 2. a grant without a synced copy
    for mac_path, access in granted_paths(device).items():
        if mac_path.endswith("/" + FOLDER_NAME):
            return Folder(device, mac_path, None, access), info
    info.update(ok=False, channel="none", error="no_access",
                message="This agent has no access to the Mac's PWA Baker folder yet.",
                permission_request={
                    "type": "file-sharing",
                    "payload": {"path": "~/" + FOLDER_NAME, "access": "WRITE", "sync": {"conflict": "NEWER"}},
                })
    return None, info


def emit(obj: dict[str, Any]) -> int:
    print(json.dumps(obj, indent=2))
    return 0 if obj.get("ok") else 1


def status(folder: Folder, info: dict[str, Any]) -> dict[str, Any]:
    raw = folder.read("status.json")
    out = dict(info, channel=folder.channel, access=folder.access, mac_path=folder.mac_path,
               local_path=str(folder.local) if folder.local else None)
    if raw is None:
        out.update(ok=False, error="not_installed",
                   message="The folder is shared but PWA Baker has not run on the Mac yet. Ask the user to install "
                           "it with: " + INSTALL_LINE)
        return out
    try:
        st = json.loads(raw)
    except ValueError:
        st = {}
    age = int(time.time() - st.get("updated_at", 0))
    out.update(ok=True, mac_status=st, status_age_seconds=age,
               mac_awake=age < STALE_SECONDS,
               ready=bool(st.get("ready")) and age < STALE_SECONDS)
    if folder.access != "write":
        out.update(ok=False, error="read_only",
                   message="Access to the folder is read-only; requests need write access.")
    elif age >= STALE_SECONDS:
        out["message"] = ("PWA Baker has not checked in for %d minutes: the Mac is asleep or the app is closed. "
                          "Requests will wait in the folder and run when it is back." % (age // 60))
    elif not st.get("ready"):
        out["message"] = "PWA Baker needs setup on the Mac: " + "; ".join(st.get("problems", []))
    return out


def submit(folder: Folder, request: dict[str, Any], icon: str | None) -> str:
    rid = "agent-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    if icon:
        if icon.startswith(("http://", "https://")):
            request["icon"] = icon
        else:
            src = Path(icon)
            if not src.is_file():
                raise SystemExit(emit({"ok": False, "error": "icon_missing", "message": "No file at " + icon}))
            rel = "icons/%s%s" % (rid, src.suffix.lower() or ".png")
            folder.write(rel, src.read_bytes())
            request["icon"] = rel
    folder.write("requests/%s.json" % rid, json.dumps(request).encode())
    return rid


def wait_result(folder: Folder, rid: str, wait: float) -> dict[str, Any]:
    deadline = time.time() + wait
    last: dict[str, Any] | None = None
    while True:
        raw = folder.read("results/%s.json" % rid)
        if raw:
            try:
                last = json.loads(raw)
            except ValueError:
                last = None
            if last and last.get("status") in ("done", "failed"):
                break
        if time.time() >= deadline:
            break
        time.sleep(2 if folder.local else 4)
    out: dict[str, Any] = {"request_id": rid, "channel": folder.channel}
    if not last:
        out.update(ok=False, status="waiting",
                   message="No answer yet. The request is in the Mac's folder and runs when PWA Baker sees it; "
                           "check later with: result " + rid)
        return out
    out.update(ok=last.get("status") == "done", status=last.get("status"), progress=last.get("progress"),
               error=last.get("error"), message=last.get("message"), result=_short(last.get("result")))
    return out


def _short(result: Any) -> Any:
    """The result without the installer's full output; a failure keeps its last lines."""
    if not isinstance(result, dict):
        return result
    short = {k: v for k, v in result.items() if k != "log_tail"}
    if result.get("log_tail") and "app_path" not in result:
        short["log_tail"] = result["log_tail"][-600:]
    return short


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", help="device id or hostname (default: the Mac most recently seen)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    p_bake = sub.add_parser("bake")
    p_bake.add_argument("url")
    p_bake.add_argument("--name")
    p_bake.add_argument("--icon", help="a picture file in this workspace, or an http(s) address")
    p_bake.add_argument("--wait", type=float, default=180)
    p_rm = sub.add_parser("uninstall")
    p_rm.add_argument("name")
    p_rm.add_argument("--wait", type=float, default=60)
    p_res = sub.add_parser("result")
    p_res.add_argument("request_id")
    args = parser.parse_args(argv)

    if not shutil.which("latchkey"):
        return emit({"ok": False, "error": "no_latchkey", "message": "latchkey is not on PATH; run this inside a Studio workspace."})
    folder, info = find_folder(args.device)
    if folder is None:
        return emit(info)
    if args.command == "status":
        return emit(status(folder, info))
    if args.command == "result":
        return emit(wait_result(folder, args.request_id, 0))
    if folder.access != "write":
        return emit(status(folder, info))
    if args.command == "bake":
        request: dict[str, Any] = {"url": args.url}
        if args.name:
            request["name"] = args.name
        rid = submit(folder, request, args.icon)
    else:
        rid = submit(folder, {"action": "uninstall", "name": args.name}, None)
    out = wait_result(folder, rid, args.wait)
    if out.get("status") == "waiting":
        out["mac"] = status(folder, info).get("message")
    return emit(out)


if __name__ == "__main__":
    sys.exit(main())
