#!/usr/bin/env python3
"""End-to-end check on a real Mac (the GitHub macOS runner): open the built app, bake through
the shared folder exactly as an agent would, and check what came out.

    python3 ci/mac_e2e.py "build/PWA Baker.app" <screenshot dir>

Expects /Applications/Chromium.app (ci/get_chromium.sh puts it there). Leaves screenshots of
the app window and the baked app's window in the screenshot dir.
"""

import json
import os
import struct
import subprocess
import sys
import time
import uuid
import zlib
from pathlib import Path

HOME = Path.home()
BOX = HOME / "PWA Baker"
APPS = HOME / "Applications" / "Chromium Apps.localized"
UD = HOME / "Library" / "Application Support" / "Chromium"
failures = []


def check(ok, what):
    print(("PASS " if ok else "FAIL ") + what, flush=True)
    if not ok:
        failures.append(what)
    return ok


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def wait_for(fn, timeout, step=0.5):
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(step)
    return fn()


def drop(request):
    rid = "e2e-" + uuid.uuid4().hex[:8]
    tmp = BOX / "requests" / (rid + ".json.tmp")
    tmp.write_text(json.dumps(request))
    tmp.rename(BOX / "requests" / (rid + ".json"))
    return rid


def result(rid, timeout=240):
    path = BOX / "results" / (rid + ".json")

    def done():
        if path.exists():
            data = json.loads(path.read_text())
            if data.get("status") in ("done", "failed"):
                return data
        return None

    return wait_for(done, timeout)


def png_pixels(path):
    """Decode an 8-bit RGB/RGBA non-interlaced PNG (what sips writes) into rows of tuples."""
    data = Path(path).read_bytes()
    pos, idat, width = 8, b"", 0
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, ctype = struct.unpack(">IIBB", chunk[:10])
            channels = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
            assert depth == 8
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * channels
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(height):
        f, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b, c = prev[x], prev[x - channels] if x >= channels else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(line[x:x + channels]) for x in range(0, stride, channels)])
        prev = line
    return rows


def icon_summary(app):
    png = "/tmp/e2e-icon.png"
    run(["sips", "-s", "format", "png", "-z", "256", "256", str(app / "Contents/Resources/app.icns"), "--out", png])
    rows = png_pixels(png)
    flat = [p for row in rows for p in row]
    rgb = [(p[0], p[0], p[0], p[1] if len(p) == 2 else 255) if len(p) <= 2 else p for p in flat]
    white = sum(1 for p in rgb if p[0] > 240 and p[1] > 240 and p[2] > 240 and (len(p) < 4 or p[3] > 200))
    corner = rows[2][2]
    return {"white": white, "transparent_corner": len(corner) in (2, 4) and corner[-1] == 0, "size": len(rows)}


def db_has(app_id):
    node_mods = HOME / ".cache" / "install-pwa-full-node" / "node_modules"
    js = ("const {ClassicLevel}=require('classic-level');"
          "const db=new ClassicLevel(process.argv[1],{keyEncoding:'utf8',valueEncoding:'buffer'});"
          "(async()=>{await db.open();const v=await db.get('web_apps-dt-'+process.argv[2]);"
          "console.log(v?v.length:0);await db.close();})().catch(e=>{console.log('ERR '+e.message);process.exit(1)})")
    r = run(["node", "-e", js, str(UD / "-" / "Sync Data" / "LevelDB"), app_id], env=dict(os.environ, NODE_PATH=str(node_mods)))
    return r.stdout.strip()


def profiles():
    try:
        state = json.loads((UD / "Local State").read_text())
    except (OSError, ValueError):
        return "no Local State"
    prof = state.get("profile", {})
    return {"info_cache": sorted(prof.get("info_cache", {})), "last_used": prof.get("last_used"),
            "app_shims": sorted(state.get("app_shims", {}))}


def init_profile():
    """Use Chromium once with the "-" profile, as the user's Mac had before (session 557)."""
    run(["open", "-na", "/Applications/Chromium.app", "--args", "--profile-directory=-", "--no-first-run",
         "--no-default-browser-check", "about:blank"])
    time.sleep(12)
    run(["pkill", "-TERM", "-f", "Chromium.app/Contents/MacOS/Chromium"])
    wait_for(lambda: "Chromium.app/Contents/MacOS/Chromium" not in run(["ps", "-axo", "command="]).stdout, 20)
    print("profiles after first use:", profiles())


def main():
    app_bundle = Path(sys.argv[1]).resolve()
    shots = Path(sys.argv[2]).resolve()
    shots.mkdir(parents=True, exist_ok=True)

    r = run([str(app_bundle / "Contents/MacOS/PWABaker"), "--render-icon", "/tmp/e2e-letter.png", "Notes Voice"])
    check(r.returncode == 0 and Path("/tmp/e2e-letter.png").exists(), "app binary draws a letter icon")

    if os.environ.get("E2E_INIT_PROFILE"):
        init_profile()
    run(["open", str(app_bundle)])
    health = wait_for(lambda: run(["curl", "-sf", "http://127.0.0.1:7247/health"]).stdout, 60)
    check('"PWA Baker"' in health, "engine answers on 127.0.0.1:7247 after opening the app")
    check(wait_for(lambda: (BOX / "README.md").exists(), 20), "shared folder created with its README")
    status = wait_for(lambda: (BOX / "status.json").exists() and json.loads((BOX / "status.json").read_text()), 90)
    check(bool(status) and status.get("ready") is True, "status.json says ready: %s" % (status and status.get("problems")))
    time.sleep(3)
    run(["screencapture", "-x", str(shots / "1-app-window.png")])

    # 1. A site with no icon of its own gets a letter icon drawn by the app.
    rid = drop({"url": "https://example.com/", "name": "Example E2E"})
    res = result(rid)
    print(json.dumps(res, indent=2)[:3000])
    check(bool(res) and res["status"] == "done", "bake through the shared folder finished")
    if res and not os.environ.get("E2E_INIT_PROFILE"):
        check(res["result"].get("prepared_profile") is True, "first bake set up Chromium's app profile itself")
        print("profiles after the first bake:", profiles())
    if not res or res["status"] != "done":
        return
    app = Path(res["result"]["app_path"])
    app_id = res["result"]["app_id"]
    check(app == APPS / "Example E2E.app" and app.is_dir(), "app bundle at %s" % app)
    check(not (BOX / "requests" / (rid + ".json")).exists(), "request file was taken")
    check(res["source"] == "folder", "result says it came from the folder")
    info = run(["plutil", "-p", str(app / "Contents/Info.plist")]).stdout
    check(app_id in info and "https://example.com/" in info, "shim Info.plist names the app id and URL")
    check(run(["codesign", "--verify", "--strict", str(app)]).returncode == 0, "shim signature verifies")
    ent = run(["codesign", "-d", "--entitlements", "-", "--xml", str(app)]).stdout + run(["codesign", "-d", "--entitlements", ":-", str(app)]).stdout
    check("disable-library-validation" in ent, "shim has the disable-library-validation entitlement")
    icons = UD / "-" / "Web Applications" / "Manifest Resources" / app_id / "Icons"
    check(sorted(int(p.stem) for p in icons.glob("*.png")) == [32, 48, 64, 96, 128, 192, 256, 512], "all eight icon sizes written")
    print("icon_source:", res["result"].get("icon_source"))
    summary = icon_summary(app)
    print("icon:", summary)
    if res["result"].get("icon_source") == "letter":
        check(summary["white"] > 500, "letter icon has a white letter (%d white px)" % summary["white"])
        check(summary["transparent_corner"], "letter icon has transparent rounded corners")
    stored = db_has(app_id)
    check(stored.isdigit() and int(stored) > 500, "Chromium's app database holds the app (%s bytes)" % stored)
    check((HOME / "Desktop" / "Example E2E.app").is_symlink(), "Desktop shortcut added")

    # 2. Launch the baked app, then bake a second one while it is open: it must be closed and reopened.
    run(["open", str(app)])
    opened = wait_for(lambda: "Example E2E.app" in run(["ps", "-axo", "command="]).stdout, 30)
    check(bool(opened), "baked app launches")
    time.sleep(8)
    run(["screencapture", "-x", str(shots / "2-baked-app-open.png")])
    print("profiles after launching the baked app:", profiles())
    ps = run(["ps", "-axo", "command="]).stdout
    print("\n".join(line[:300] for line in ps.splitlines() if "Chromium" in line or "Example E2E" in line))

    rid2 = drop({"url": "https://www.wikipedia.org/", "name": "Wiki E2E"})
    res2 = result(rid2)
    print(json.dumps({k: v for k, v in (res2 or {}).items() if k != "request"}, indent=2)[:3000])
    check(bool(res2) and res2["status"] == "done", "second bake with a web app open finished")
    if res2 and res2["status"] == "done":
        check("Example E2E" in (res2["result"].get("closed_apps") or []), "the open app was closed for the bake")
        check("Example E2E" in (res2["result"].get("reopened_apps") or []), "and reopened afterwards")
        print("wiki icon_source:", res2["result"].get("icon_source"), icon_summary(Path(res2["result"]["app_path"])))
    time.sleep(8)
    run(["screencapture", "-x", str(shots / "3-after-second-bake.png")])

    # 3. Refusals come back as results, and uninstall removes the app.
    rid3 = drop({"url": "file:///etc/passwd"})
    res3 = result(rid3, 30)
    check(bool(res3) and res3.get("error") == "bad_url", "a file:// request is refused with bad_url")
    rid4 = drop({"action": "uninstall", "name": "Wiki E2E"})
    res4 = result(rid4, 60)
    check(bool(res4) and res4["status"] == "done" and not (APPS / "Wiki E2E.app").exists(), "uninstall removed the app")

    status = json.loads((BOX / "status.json").read_text())
    check([a["name"] for a in status["apps"]] == ["Example E2E"], "status.json lists the remaining app: %s" % status["apps"])
    log = HOME / "Library" / "Logs" / "pwa-baker" / "engine.log"
    print("---- engine log ----")
    print(log.read_text()[-4000:] if log.exists() else "(none)")


if __name__ == "__main__":
    try:
        main()
    finally:
        print("\n%d failure(s)" % len(failures))
        for f in failures:
            print("  - " + f)
    sys.exit(1 if failures else 0)
