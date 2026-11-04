# PWA Baker (Mac app)

A Mac app that turns a web address into a Chromium web app: its own window, name and Dock icon,
listed in `chrome://apps`, with "App info" and "Uninstall" in its menu. Bake from the app's
window, or let a Studio agent ask for apps through a shared folder. The agent half is the
`bake-pwa-on-mac` skill in `.agents/skills/`.

**Start here for the whole picture:** [`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md).
Day-two work (logs, restarts, errors): [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## Install (on the Mac)

Only this folder is needed on the Mac, so fetch just it:

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/boweiliu/pwa-baker-template ~/code/pwa-baker-src \
  && cd ~/code/pwa-baker-src && git sparse-checkout set mac-apps/pwa-baker && mac-apps/pwa-baker/install.sh
```

Needs the Xcode command line tools (`xcode-select --install`), Node (`brew install node`) and
Chromium at `/Applications/Chromium.app` (the app's Setup tab says how to get each). Optional:
`dockutil` for Dock pinning, `cloudflared` for the public link. `install.sh` builds the app
from source, puts it in `~/Applications` and opens it. The app adds itself as a login item on
first run, and keeps running in the menu bar when its window is closed.

## How agents reach it

**Shared folder (the normal way).** The app watches `~/PWA Baker/`. Share that folder with a
Studio agent once, through Studio's file-sharing approval. The agent writes
`requests/<id>.json`, the app bakes and writes `results/<id>.json`, and `status.json` says
whether the Mac is up. The folder's own `README.md` is the full protocol. With a synced copy,
requests made while the Mac sleeps run when it wakes. Where Studio cannot keep a synced copy,
the agent writes through Studio's file server instead, which needs the Mac awake with Studio
open.

**Public link (fallback).** The Agents tab can open a Cloudflare quick tunnel to the app's local
API. Every route but `/health` needs the password from `~/.config/pwa-baker/config.json`. The
link changes each time; the password does not.

## Layout

- `app/`: the SwiftUI app (window + menu bar). Its binary also draws letter icons.
- `engine/pwa_baker/`: the python engine the app runs. It holds the request queue, the
  shared-folder watcher, the local API, and the bundled installer `resources/install-pwa-full.sh`
  with its Chromium calibration template.
- `ci/`: a Mac check that builds the app, opens it, and bakes through the shared folder with a
  real Chromium snapshot. `ci/github-actions-mac.yml` runs it on a GitHub Mac runner.

## Develop

```bash
python3 -m pytest engine/tests     # engine, with a stand-in installer; runs anywhere
./build.sh                         # build/PWA Baker.app (Mac only)
```
