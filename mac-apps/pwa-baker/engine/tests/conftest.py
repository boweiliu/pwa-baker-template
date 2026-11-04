"""Point every engine path at a scratch directory before the engine is imported.

The engine reads its paths once, at import, from PWA_BAKER_* variables. The installer is a
stand-in that records its arguments and builds a minimal app bundle, so these tests run on
any machine; the real installer is exercised on a Mac by tests/test_mac_e2e.py.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Shared by every load of this file (the agent-skill tests load it too), since the engine reads
# the paths once.
ROOT = Path(os.environ.get("PWA_BAKER_TEST_ROOT") or tempfile.mkdtemp(prefix="pwa-baker-test-"))
os.environ["PWA_BAKER_TEST_ROOT"] = str(ROOT)
FAKE_INSTALLER = ROOT / "fake-installer.sh"
FAKE_LOG = ROOT / "fake-installer.log"

ENV = {
    "PWA_BAKER_CONFIG": str(ROOT / "config" / "config.json"),
    "PWA_BAKER_LOG_DIR": str(ROOT / "logs"),
    "PWA_BAKER_STATE_DIR": str(ROOT / "state"),
    "PWA_BAKER_APPS_DIR": str(ROOT / "Applications" / "Chromium Apps.localized"),
    "PWA_BAKER_CHROMIUM_USER_DATA": str(ROOT / "chromium-profile"),
    "PWA_BAKER_CHROMIUM_APP": str(ROOT / "Chromium.app"),
    "PWA_BAKER_DESKTOP_DIR": str(ROOT / "Desktop"),
    "PWA_BAKER_INSTALLER": str(FAKE_INSTALLER),
    "FAKE_INSTALLER_LOG": str(FAKE_LOG),
}
os.environ.update(ENV)

FAKE_INSTALLER.write_text(r"""#!/bin/bash
# Stand-in for install-pwa-full.sh: records its arguments, builds a bundle with an Info.plist.
set -eu
printf '%s\n' "$@" > "$FAKE_INSTALLER_LOG"
URL="$1"; shift; NAME=""; ICON=""
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="$2"; shift 2;;
    --icon) ICON="$2"; shift 2;;
    --browser-app) shift 2;;
    *) shift;;
  esac
done
[ -n "$NAME" ] || NAME="Site"
if [ "$URL" = "https://fails.example/" ]; then echo "proto synthesis failed" >&2; exit 1; fi
APP="$PWA_BAKER_APPS_DIR/$NAME.app"
mkdir -p "$APP/Contents"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>
<key>CrAppModeShortcutID</key><string>abcdefghijklmnopabcdefghijklmnop</string>
<key>CrAppModeShortcutURL</key><string>$URL</string>
</dict></plist>
PLIST
echo "name: $NAME"
echo "start_url: $URL"
echo "icon_source: ${ICON:+given}"
echo "Created: $APP"
echo "App id:  abcdefghijklmnopabcdefghijklmnop"
""")
FAKE_INSTALLER.chmod(0o755)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def clean_dirs():
    """Each test starts with an empty Mac: no apps, no settings, Chromium present."""
    for key in ("PWA_BAKER_APPS_DIR", "PWA_BAKER_STATE_DIR", "PWA_BAKER_DESKTOP_DIR", "PWA_BAKER_CHROMIUM_APP"):
        path = Path(ENV[key])
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
    profile = Path(ENV["PWA_BAKER_CHROMIUM_USER_DATA"])
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "Local State").write_text(json.dumps({"profile": {"info_cache": {"-": {}}}}))
    config_file = Path(ENV["PWA_BAKER_CONFIG"])
    if config_file.exists():
        config_file.unlink()
    if FAKE_LOG.exists():
        FAKE_LOG.unlink()
    yield


@pytest.fixture
def dropbox_dir(tmp_path):
    return tmp_path / "PWA Baker"


@pytest.fixture
def engine_parts(dropbox_dir):
    from pwa_baker import config
    from pwa_baker.dropbox import DropBox
    from pwa_baker.jobs import JobRunner

    cfg = config.Config()
    cfg.data["dropbox_dir"] = str(dropbox_dir)
    cfg.data["add_to_dock"] = False
    cfg.save()
    lines = []
    runner = JobRunner(cfg, lines.append)
    dropbox = DropBox(cfg, runner, lines.append)
    dropbox.prepare()
    return cfg, runner, dropbox


def installer_args():
    return FAKE_LOG.read_text().splitlines() if FAKE_LOG.exists() else []


def read_json(path):
    return json.loads(Path(path).read_text())
