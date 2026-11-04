---
title: "PWA Baker"
description: "Turn any web address into a real Chromium web app on your Mac (own window, name and Dock icon), and let your Studio agent bake them for you through a shared folder."
thumbnail: "template.svg"
version: v1
format: v2
---

# PWA Baker

This file is the manifest for the **PWA Baker** template (slug:
`pwa-baker`). It is the one document a future agent reads to understand,
present, and adapt this template. If you are an agent in a workspace that was
created from this template, this file is your script: read all of it, then
follow "How to adapt it" below.

## What it is

Turn any web address into a real Chromium web app on your Mac (own window, name and Dock icon), and let your Studio agent bake them for you through a shared folder.

PWA Baker turns a web address into a real Chromium web app on the user's Mac: its own window, its own name and its own Dock icon, listed in `chrome://apps` with "App info" and "Uninstall" in its menu. It is a native macOS menu bar app (SwiftUI) with a python engine behind it, plus an agent skill. The user can bake from the app's window, or ask their Studio agent ("make me a Dock app for this page", "turn my Studio dashboard into a desktop app") and the agent does it through a shared folder, `~/PWA Baker`, that Studio's file sharing gives it. The engine bakes the app by writing Chromium's WebApp record directly and building a signed app shim, a full-fidelity install with no Chromium "Install" click. When it works, the user sees the new app appear in their Dock and on their Desktop a few seconds after asking.

## How it works

The snapshot includes these paths (each is a repo-root-relative path copied
from the original agent onto a clean default-workspace-template base):

- `.agents/skills/bake-pwa-on-mac`

- `.agents/skills/bake-pwa-on-mac` -- the agent skill. `SKILL.md` tells the agent how to check the connection, ask for the folder, bake and uninstall. Its `python/` project is a stdlib-only helper (`bake_pwa_on_mac.py`) that writes `requests/<id>.json` into the Mac's `~/PWA Baker` folder and reads `results/<id>.json` and `status.json` back. It reaches the folder two ways: a synced copy under `~/synced_folders` when Studio keeps one, otherwise the Studio file server through `latchkey`. It is a member of the root uv workspace (glob `.agents/skills/*/python`), so `uv.lock` carries its entry.
- `mac-apps/pwa-baker` -- the Mac app. `app/` is the SwiftUI menu bar app; `engine/pwa_baker/` is the python engine it runs (request queue, shared-folder watcher, local API, and the bundled installer `resources/install-pwa-full.sh` with its Chromium calibration template); `ci/` is a Mac end-to-end check that also runs on a GitHub Mac runner; `docs/HOW-IT-WORKS.md` and `docs/OPERATIONS.md` are the design and day-two docs. It is built from source on the Mac by `install.sh` (needs the Xcode command line tools). The engine's python tests (`engine/tests/test_pwa_baker_*.py`) use a stand-in installer and run on Linux.

At runtime nothing in the Studio workspace runs on its own: no supervisord programs, no ports, no `forward_port.py` registration, no LLM calls. The skill's helper runs only when the agent calls it. The flow is: the agent writes a request into the shared folder; Studio syncs it to the Mac; the PWA Baker app on the Mac picks it up, bakes the app and writes the result; the helper reads the answer. `status.json` in the same folder is a heartbeat the app refreshes every minute, which is how the agent knows the Mac is awake. If the folder cannot be shared, the Mac app's Agents tab can open a public link (a Cloudflare quick tunnel to the app's local API) as a fallback.

## Recipe

This template is version `v1`. It is not a fork of the
workspace it came from -- it is DERIVED from it by a recipe: include these
paths, leave these out, apply these published-version rules. An update re-runs
the recipe against the current workspace and publishes the result as the next
version, so anything excluded stays excluded even though it still exists in the
source workspace.

The recipe is machine-read, so it lives in the sibling
[`template.toml`](template.toml) -- its `[recipe]` table -- along with
the structured requirements and the environment this template needs
installed. That file is authoritative for all of it; this one holds the prose.

## Requirements

Everything the adopting agent must deal with before this template is really
theirs. Two kinds of entry, handled at different times:

- **Activation** -- what must be SET UP before anything runs, in the
  machine-readable `requires_` forms below. The adopting agent acts on these
  ITSELF, first, before asking anything.
- **Adaptation** -- what must be DECIDED or REWIRED, in prose. Worked through
  interactively with the user, after activation.


- requires_permission: file-sharing / WRITE access to `~/PWA Baker` on the user's Mac, ideally with syncing on (user-approved; the adopting agent initiates this itself by following the skill's "1. Check the connection": a `file-sharing` permission request posted to `latchkey-self.invalid/permission-requests`, which is a Studio file-sharing grant and not a latchkey service scope)

- **The Mac app must be installed on the Mac.** An adopter needs a Mac with Chromium at `/Applications/Chromium.app` (an arm64 snapshot build), Node (`brew install node`) and the Xcode command line tools (`xcode-select --install`). The user runs the one-line install from `mac-apps/pwa-baker/README.md` in Terminal on the Mac (it fetches only `mac-apps/pwa-baker` from the public template repo and builds the app from source). The agent cannot do this for them; the skill's `not_installed` branch says what to tell the user. The app's Setup tab lists anything still missing.
- **Studio's synced copy is not available on every workspace host.** Where it is not, the helper uses Studio's file server, which needs the Mac awake with Studio open. Decide with the user whether that is acceptable; if not, the public-link fallback in the skill is the alternative.
- **The Chromium app template was captured on Chromium 158 and checked on 159.** A much newer Chromium may need the calibration template regenerated with `engine/pwa_baker/resources/calib/regen.sh`; `docs/OPERATIONS.md` says when.
- **The install line points at the template's public repository.** If the adopter keeps their own copy of the Mac app elsewhere (for example a private repository), they should change the install line in the skill's `not_installed` branch to match.

## Environment

What this template needs INSTALLED, beyond what the template already has.
Declared in `template.toml`'s `[environment]` table; an adopting agent
converges it at ITS OWN pinned apt snapshot timestamp, so package versions come
out consistent with the rest of that agent's environment rather than frozen to
whatever this publisher happened to have.

Nothing extra -- runs on the stock workspace environment. Everything PWA Baker needs is installed on the user's Mac, not in the Studio workspace: Chromium at `/Applications/Chromium.app`, Node, and the Xcode command line tools (see Requirements). The skill's helper uses only the python standard library.

## How to adapt it

Instructions for the NEXT agent -- the one adapting this template into a
new agent. This is the `use-template` skill's template path; in short:

1. Read this entire file first, especially "Requirements" below. It holds two
   kinds of entry and they are handled at different times: the machine-readable
   `requires_` lines are ACTIVATION (set them up before anything runs), and
   the prose bullets are ADAPTATION (decide or rewire them afterwards).
2. Present the template to the user in plain, non-technical language: what
   it is, what it does, and what it needs from them (name the activation
   requirements).
3. Ask whether they want to use the same connectors (e.g. their own Slack).
   If YES: ACTIVATE FIRST -- initiate every `requires_permission` line NOW
   via a latchkey permission request (see the `connect-external-service` skill; the request
   opens the approval/login flow in the Imbue Studio app), wire up any
   `requires_secret` values, start the services, and get the app showing
   THE USER'S OWN DATA. Done for a data-backed app means the user can open it
   and see their own data -- NOT that a service starts or an endpoint returns
   200. Then tell them it is live and to take a look.
4. Only AFTER that (or immediately, if they chose different connectors -- the
   swap is then the first adaptation) ask: "How do you want to adapt it?"
5. Work through each requirement interactively, one at a time. Translate each
   into plain language, ask for a decision only when you genuinely need one,
   and resolve the obvious ones yourself.
6. When done, append a dated entry to "Adaptation history" below (never
   rewrite earlier entries) and commit.

## Publication history

This template's changelog: what each published version changed. The PUBLISHER
appends one entry per version (newest last); earlier entries are never rewritten.
This is distinct from "Adaptation history" below, which is the ADOPTERS' log.

### v1 (2026-11-04) -- first publication: the bake-pwa-on-mac agent skill and the PWA Baker Mac app it drives.

## Adaptation history

Each agent that adapts this template appends one dated entry below. Earlier
entries are never rewritten.
