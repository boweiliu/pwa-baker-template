# PWA Baker: day-two operations

What to do once it is set up. For how it fits together, read `docs/HOW-IT-WORKS.md` first; this
page does not repeat it. Items marked **(unverified)** follow from the code but were not run.

## Is it working?

- On the Mac: the window's top line says "Ready to bake". The menu bar icon's first line says
  "Ready, N apps".
- From an agent: `python3 .agents/skills/bake-pwa-on-mac/python/bake_pwa_on_mac_skill/bake_pwa_on_mac.py status`
  prints `"ok": true, "ready": true, "mac_awake": true`. `status_age_seconds` over 300 means the
  Mac is asleep or the app is closed.

## Logs and records

- `~/Library/Logs/pwa-baker/engine.log`: every request, its progress, and its outcome (Setup tab,
  Open Log).
- `~/Library/Application Support/PWA Baker/history.jsonl`: one line per finished request, with
  the raw request. The Activity tab shows the last 50, with "What was asked" and the installer
  output.
- `~/PWA Baker/results/<id>.json`: the answer to each folder request. Pruned after 30 days.

## Restart

- Quit from the menu bar icon (Quit PWA Baker) and open it again from `~/Applications`. The
  engine stops with the app: it watches the app's process and exits within 2 seconds of it going.
- If the engine stops on its own, the app restarts it. After 5 stops in a minute it gives up,
  and the window shows "Not running" with Try Again and Open Log.

## Update the app

```bash
cd ~/code/pwa-baker-src && git pull && mac-apps/pwa-baker/install.sh
```

This rebuilds, quits the running copy, and installs and opens the new one. Settings, the
password and history are kept (they live outside the app).

## What an error means

Every failure has a short `error` code plus a plain `message`. The codes:

| Code | Meaning | Fix |
| --- | --- | --- |
| `url_required`, `bad_url` | No address, or not http(s) | Send an http(s) address |
| `bad_name`, `name_required` | Name empty after cleaning, or missing for an uninstall | Use a plain name |
| `bad_icon`, `icon_missing` | Icon is not http(s) or a file in the folder's `icons/`; or the file never arrived (waits 60 s first) | Send a fetchable address, or put the picture in `icons/` |
| `bad_request`, `bad_request_id`, `bad_action`, `bad_json` | Request file is not a JSON object, has an odd file name, an unknown action, or is not JSON 15 s after arriving | Fix the file |
| `chromium_missing` | No `/Applications/Chromium.app` | Setup tab has the download steps |
| `chromium_running` | Chromium is open and "Close open web apps for a moment" is off | Turn it on, or close Chromium |
| `chromium_locked`, `chromium_relocked` | Chromium would not let go of its app list, or came back before the bake | Quit Chromium fully, retry |
| `profile_not_ready` | First-bake profile setup did not finish within 30 s | Open Chromium once, quit, retry |
| `installer_failed`, `installer_timeout`, `installer_missing` | The bundled installer failed (its last lines are in `result.log_tail`), took over 5 minutes, or is missing | Read `log_tail`; reinstall for `installer_missing` |
| `not_found`, `not_a_web_app` | Uninstall of a name that is not there, or not a Chromium web app (left alone) | Check the name in the Apps tab |
| `internal_error` | Anything unexpected | engine.log |

An agent that sees `"status": "waiting"` got no answer yet. Most often the Mac is asleep or Studio
is closed (without a synced copy nothing waits; see HOW-IT-WORKS section 5).

## The public link and its password

- Turn it on and off from the Agents tab. It needs `cloudflared` (`brew install cloudflared`). The
  link changes every time it is turned on.
- The password is `token` in `~/.config/pwa-baker/config.json` (only this Mac user can read it).
  To change it **(unverified)**: quit the app, delete the `token` line, and reopen. A new one is
  generated on start (`engine/pwa_baker/config.py`, search "token_urlsafe").

## Safe limits

One bake at a time; requests queue. Request bodies up to 64 KB; icons up to 5 MB. A bake takes a
few seconds, plus about 10 when open web apps are closed and reopened.

## When Chromium updates

The app template came from Chromium 158 and was checked on 159. If baked apps start opening as
plain tabs after a big Chromium update, recapture the template **(unverified with this app)**: in
Chromium, install the demo PWA at https://khmyznikov.com/pwa-install/, quit Chromium, run
`engine/pwa_baker/resources/calib/regen.sh`, then rebuild with `./install.sh`.

## Remove PWA Baker **(unverified)**

Quit it, delete `~/Applications/PWA Baker.app`, and remove it from System Settings > General >
Login Items. `~/PWA Baker/`, `~/.config/pwa-baker/` and `~/Library/Logs/pwa-baker/` can be deleted
too. Baked apps stay until removed in Finder (or remove them from the app first).

## Changing the code

Run the engine tests anywhere (`README.md`, search "Develop"). Check Mac behaviour on a real
Mac with `ci/mac_e2e.py`, for example through `ci/github-actions-mac.yml`.
