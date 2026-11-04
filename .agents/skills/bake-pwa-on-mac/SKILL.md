---
name: bake-pwa-on-mac
description: "Turn a web address into a Chromium web app on the user's Mac (its own window, name and Dock icon) through the PWA Baker app, by writing a request into the Mac's shared ~/PWA Baker folder. Use when the user asks for a PWA, a Dock app or a desktop app for a URL or one of their Studio apps, or to remove one."
metadata:
  author: bowei
---

# Bake a web app on the Mac

PWA Baker is a Mac app (source: `mac-apps/pwa-baker/` in this workspace; start with its `docs/HOW-IT-WORKS.md`). It watches `~/PWA Baker/` on
the Mac. Studio's file sharing gives this agent that folder, ideally as a synced copy in this
workspace, so asking for an app is writing a file. No tunnel, no token, nothing for the user to
paste. The helper below does the file work and prints one JSON object per command.

```bash
H=.agents/skills/bake-pwa-on-mac/python/bake_pwa_on_mac_skill/bake_pwa_on_mac.py
python3 $H status
python3 $H bake "https://example.com/" --name "Example" [--icon <picture file here, or https URL>]
python3 $H uninstall "Example"
python3 $H result <request_id>      # a request that was still waiting
```

## 1. Check the connection

Run `status`. Act on what it says:

- `"channel": "none"` (`no_access`): ask for the folder. Send the request in a tool call of its
  own, output untouched (the Studio app renders it), with the `payload` the helper printed:

  ```bash
  latchkey curl -H "X-Latchkey-Device: <device from status>" -XPOST http://latchkey-self.invalid/permission-requests \
    -H 'Content-Type: application/json' \
    -d '{"agent_id": "'"${MINDS_CHAT_ID:-$MNGR_AGENT_ID}"'", "type": "file-sharing", "payload": {"path": "~/PWA Baker", "access": "WRITE", "sync": {"conflict": "NEWER"}}, "rationale": "To bake web apps on your Mac, I need to drop requests into your PWA Baker folder. Keeping it synced lets requests wait while the Mac sleeps."}'
  ```

  Then wait for the approval message. The synced copy can take a moment to appear; run
  `status` again until it shows `"channel": "synced"` (or `"file-server"` if the user turned syncing
  off, which works only while the Mac is awake with Studio open).
- `not_installed`: the folder exists but the app never ran. Tell the user to run this in Terminal on
  the Mac, then try again:
  `git clone --depth 1 --filter=blob:none --sparse https://github.com/boweiliu/pwa-baker-template ~/code/pwa-baker-src && cd ~/code/pwa-baker-src && git sparse-checkout set mac-apps/pwa-baker && mac-apps/pwa-baker/install.sh`
- `"mac_awake": false`: the Mac is asleep or PWA Baker is closed. A request still works: it
  waits in the folder and runs when the Mac is back. Say so instead of waiting on it.
- `"ready": false` with `mac_status.problems`: something is missing on the Mac (Chromium,
  Node). Pass the fix on; the app's Setup tab shows the same list.

## 2. Bake

`bake` waits up to 3 minutes for the answer. A bake takes a few seconds, plus about 10 if open
Chromium web apps had to be closed and reopened (Chromium locks its app list while running).

- `"ok": true`: tell the user the app's name and that it is in their Dock and on their Desktop.
  Mention `result.closed_apps` if any (they were reopened) and `result.icon_note` if present.
- `"status": "waiting"`: the Mac has not picked it up (asleep, or sync is slow). Give the user the
  `request_id`; `result <id>` checks later.
- `"ok": false`: `message` says why in plain words, `error` is a stable code
  (`bad_url`, `chromium_running`, `installer_failed`, ...). `installer_failed` includes the
  installer's last lines in `result.log_tail`.

Names: baking a name that exists replaces that app. Icons: without one, the site's own icon is
used, or a letter icon. An icon URL must work without signing in (share links do not), so for
a Studio app's icon pass a picture file from this workspace with `--icon`; the helper copies it
into the folder's `icons/`.

Studio app links (share-gateway URLs) are fine as the URL: the app asks the user to sign in once on
first launch and remembers it. Chromium web apps show an "App update available" badge for
sites without a web manifest; it is cosmetic.

## 3. The folder, if the helper is not enough

`~/PWA Baker/README.md` on the Mac is the protocol: write `requests/<id>.json`
(`{"url", "name"?, "icon"?}` or `{"action": "uninstall", "name"}`), read `results/<id>.json`
(`status` queued, running, done or failed). `status.json` is refreshed every minute while the
app runs and lists the baked apps.

## Fallback: the public link

If the folder cannot be shared, the user can turn on "Public link" in the app's Agents tab and
paste the link and password. Then `POST <link>/bake {"url", "name"?, "icon"?}` with
`Authorization: Bearer <password>` (waits for the result; `"wait": false` returns a job to poll
at `GET /jobs/<id>`). The link changes each time it is turned on; never save it.
