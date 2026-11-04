# PWA Baker: how it is set up, and how a request travels to the Mac and back

Entry point. Reads top down with no prior context. It cites files instead of repeating them,
each with a **search term** to grep for. Paths are relative to this folder
(`mac-apps/pwa-baker/` in the workspace) unless they start with `.agents/`.

## 1. What it is

A Chromium web app (a "PWA") is a Mac app bundle that opens one website in its own window, with
its own name, Dock icon and "App info / Uninstall" menu. Chromium normally makes one when you
click "Install" on a site. PWA Baker makes them from any web address without that click. It
writes Chromium's app record directly and builds a signed app bundle for it. You drive it from
its window, or a Studio agent in the cloud drives it.

The recipe and its pitfalls are in the installer's comments,
`engine/pwa_baker/resources/install-pwa-full.sh`. Its numbered steps begin at
**"1. fetch manifest"**.

## 2. Setting it up, top down

**2a. The Mac (once).** Run the install line from `README.md` (search **"Install (on the Mac)"**).
It builds the app, puts it in `~/Applications` and opens it. On first run the app adds itself
as a login item and creates `~/PWA Baker/`. Its Setup tab lists anything missing
(`engine/pwa_baker/checks.py`, search **"def run_checks"**). On a Chromium that never opened its
app profile, the first bake opens Chromium for a moment to set that profile up
(`engine/pwa_baker/baker.py`, search **"def prepare_profile"**).

**2b. Studio (once per workspace).** The agent asks Studio for write access to `~/PWA Baker` on
the Mac, and the user approves. The exact request is in
`.agents/skills/bake-pwa-on-mac/SKILL.md`, search **"permission-requests"**. Studio's general
rules are in `.agents/skills/file-sharing/SKILL.md`, search **"Folders the user keeps synced"**.

**2c. The agent.** From then on, "make me a PWA of X" is one helper call (SKILL.md, search
**"python3 $H bake"**).

## 3. How one request travels, hop by hop

```
agent in a Studio workspace
  | 1. helper writes requests/<id>.json
  v
latchkey gateway --> Imbue Studio desktop app on the Mac      [or: Studio's synced copy]
  | 2. the file lands in ~/PWA Baker/requests/
  v
PWA Baker app on the Mac --> its engine (python, child process)
  | 3. folder watcher picks it up within ~1 s, checks it, deletes it
  | 4. one queue, one bake at a time
  | 5. close open Chromium web apps if Chromium holds its app list, run the installer,
  |    add Dock icon + Desktop shortcut, reopen what was closed
  | 6. writes results/<id>.json (queued -> running -> done | failed)
  v
back the same way: the helper reads results/<id>.json and reports
```

1. **The helper** finds the Mac and the agent's grants, and picks a route
   (`.agents/skills/bake-pwa-on-mac/python/bake_pwa_on_mac_skill/bake_pwa_on_mac.py`, search
   **"def find_folder"**).
2. **Two routes to the Mac** (same file, search **"class Folder"**). The *synced copy* is plain
   file writes, and requests wait while the Mac sleeps. The *file server* is an HTTP upload
   relayed by the Studio app on the Mac; it needs the Mac awake. The helper uses the file
   server whenever the synced copy is empty.
3. **The folder watcher** waits out half-synced files, refuses anything unsafe, and answers
   every request (`engine/pwa_baker/dropbox.py`, search **"def _take"**; rules in
   `engine/pwa_baker/validate.py`). The wire format is the **"README ="** text in `dropbox.py`,
   which the engine also writes into `~/PWA Baker/README.md`.
4. **The queue** (`engine/pwa_baker/jobs.py`, search **"class JobRunner"**) runs one bake at a
   time. It records every finished request, with the raw request, in
   `~/Library/Application Support/PWA Baker/history.jsonl`.
5. **The bake** (`engine/pwa_baker/baker.py`, search **"def bake("**). Chromium locks its app list
   while it runs. So the engine closes open web apps gracefully, waits until the lock is really
   free (search **"def lock_free"**), bakes, and reopens them. Letter icons come from
   `app/Sources/IconRenderer.swift`, search **"renderLetterIcon"**.
6. **The answer** (`dropbox.py`, search **"def write_status"** for the heartbeat). Failures carry a
   stable `error` code; the list is in `docs/OPERATIONS.md`, search **"What an error means"**.

The app's window uses the same queue, over a local address (`engine/pwa_baker/server.py`; the
route list is its opening comment). So does the optional public link
(`engine/pwa_baker/tunnel.py`).

## 4. Where things live on the Mac

- App: `~/Applications/PWA Baker.app` (engine and installer bundled in `Contents/Resources/engine/`).
- Shared folder: `~/PWA Baker/`. Baked apps: `~/Applications/Chromium Apps.localized/<Name>.app`.
- Settings and the public-link password: `~/.config/pwa-baker/config.json`.
- Logs: `~/Library/Logs/pwa-baker/engine.log`.

## 5. Known gaps

- Studio's synced copy is not available on every workspace host. Where it is missing, agents use
  the file server, and requests fail while the Mac sleeps instead of waiting.
- The Chromium app template was captured from Chromium 158 and checked on 159. A much newer
  Chromium may need it recaptured (`engine/pwa_baker/resources/calib/regen.sh`).
- Baked apps for sites without a web manifest show a cosmetic "App update available" in their
  menu.
