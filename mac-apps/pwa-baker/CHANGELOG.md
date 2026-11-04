# Changelog

## 2.0.0 (2026-11-04)

First version as a Mac app; replaces the session 585 background script.

- A Mac app with a window and a menu bar icon: bake from a web address, see and remove your web
  apps, see every request (yours and agents'), a setup checklist, settings. Starts at login.
- Agents ask through a shared folder (`~/PWA Baker`) approved in Studio, instead of a tunnel and a
  password pasted into chat. The tunnel stays as an optional "public link".
- One queue for every request, so two bakes never collide.
- Letter icons are drawn by the app itself; no Pillow download. Sites' apple-touch-icons are used
  when there is no manifest icon.
- Fixed: the installer failed under the Mac's built-in shell; an error page could be taken as an
  icon; a fresh Chromium opened baked apps as browser tabs; removing an app left its Desktop
  shortcut on some paths.
- Chromium is reopened after a bake that had to close it.
- The agent helper uses Studio's file server when the synced copy of the folder is empty.
