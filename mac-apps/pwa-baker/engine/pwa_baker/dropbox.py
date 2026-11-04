"""The shared folder agents use to ask this Mac for apps.

The user shares ~/PWA Baker with a Studio agent once (Studio asks them to approve it, and can
keep a synced copy in the agent's workspace). After that:

    requests/<id>.json   the agent writes {"url": ..., "name": ..., "icon": ...}
    results/<id>.json    PWA Baker writes queued, then running, then done or failed
    icons/               the agent may put icon pictures here and name them in "icon"
    status.json          refreshed every minute: whether this Mac is ready, and its apps
    README.md            these instructions, for whichever agent opens the folder

No tunnel, no token: who may write here is whatever the user approved in Studio.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import VERSION, baker, checks, config
from .jobs import JobRunner
from .validate import RequestError, clean_job_id, parse_request

POLL_SECONDS = 1.0
STATUS_SECONDS = 60.0
# A request that does not parse yet may still be arriving; give the sync this long to finish it.
PARTIAL_GRACE_SECONDS = 15.0
ICON_GRACE_SECONDS = 60.0
RESULTS_KEEP_DAYS = 30

README = """# PWA Baker drop box

This folder belongs to the PWA Baker app on {user}'s Mac. Writing a request file here asks
that Mac to turn a web address into a Chromium web app (its own window and Dock icon).

## Ask for an app

Write `requests/<id>.json`, where `<id>` is any new name made of letters, digits, `-`, `_`:

```json
{{"url": "https://example.com/", "name": "Example", "icon": "icons/example.png"}}
```

- `url` (required): http or https address the app opens.
- `name` (optional): the app's name; defaults to the site's own name.
- `icon` (optional): an http(s) picture address the Mac can fetch without signing in, or a
  picture you put in this folder's `icons/` folder. Without one the site's icon is used, or a
  letter icon when the site has none.

Write the file in one go (or write `<id>.json.tmp` and rename it). Baking the same name again
replaces that app. To remove one: `{{"action": "uninstall", "name": "Example"}}`.

## Read the answer

PWA Baker picks the request up within a second or two of it arriving on the Mac, deletes it,
and writes `results/<id>.json`. Its `status` goes `queued`, `running`, then `done` or
`failed`. A failed result has a short `error` code and a `message` to pass on. A done bake
has `result.app_path` and `result.name`. `request` holds what you wrote.

## Is the Mac there?

`status.json` is rewritten every minute while PWA Baker runs (`updated_at`, seconds since
1970). If it is more than a few minutes old the Mac is asleep, offline, or the app is closed:
requests wait here and run when it is back.
"""


def _age(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return 0.0


def _write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


class DropBox:
    def __init__(self, cfg: "config.Config", runner: JobRunner, log: Callable[[str], None]) -> None:
        self.cfg = cfg
        self.runner = runner
        self.log = log
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_status = 0.0
        self.last_error: Optional[str] = None

    @property
    def root(self) -> Path:
        return self.cfg.dropbox_dir

    def prepare(self) -> None:
        for sub in ("requests", "results", "icons"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        readme = README.format(user=os.environ.get("USER", "the user"))
        path = self.root / "README.md"
        if not path.exists() or path.read_text(errors="replace") != readme:
            path.write_text(readme)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="pwa-baker-dropbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.cfg.get("dropbox_enabled"):
                try:
                    self.prepare()
                    self.scan()
                    if time.time() - self._last_status >= STATUS_SECONDS:
                        self.write_status()
                        self.prune_results()
                    self.last_error = None
                except Exception as exc:  # noqa: BLE001 - keep watching; the app shows the error
                    if self.last_error != repr(exc):
                        self.log("drop box error: %r" % exc)
                    self.last_error = repr(exc)
            self._stop.wait(POLL_SECONDS)

    def scan(self) -> int:
        """Pick up every complete request file; returns how many were taken."""
        taken = 0
        requests = self.root / "requests"
        for path in sorted(requests.glob("*.json")):
            if path.name.startswith("."):
                continue
            if self._take(path):
                taken += 1
        return taken

    def _take(self, path: Path) -> bool:
        stem = path.stem
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            if not path.exists() or _age(path) < PARTIAL_GRACE_SECONDS:
                return False
            raw = {"unreadable": True}
            error: Optional[RequestError] = RequestError("bad_json", "The request file is not valid JSON.")
        else:
            error = None
        try:
            job_id = clean_job_id(stem)
        except RequestError as exc:
            job_id = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in stem)[:80] or "request"
            error = error or exc
        result_path = self.root / "results" / (job_id + ".json")
        action = None
        if error is None:
            try:
                action = parse_request(raw, self.root, config.APPS_DIR)
            except RequestError as exc:
                # An icon named in the request may still be syncing over; wait for it a while.
                if exc.code == "icon_missing" and _age(path) < ICON_GRACE_SECONDS:
                    return False
                error = exc
        try:
            path.unlink()
        except OSError:
            pass
        if error is not None or action is None:
            job = self.runner.record_rejected("folder", raw, error, job_id=job_id)  # type: ignore[arg-type]
            _write_json(result_path, job)
            self.log("refused request %s: %s" % (job_id, error.code if error else "?"))
            return True

        def write_result(job: dict[str, Any], target: Path = result_path) -> None:
            _write_json(target, job)
            if job["status"] in ("done", "failed"):
                self.write_status()

        self.runner.submit(action, "folder", raw, job_id=job_id, listener=write_result)
        return True

    def write_status(self) -> None:
        self._last_status = time.time()
        found = checks.run_checks()
        status = {
            "app": "PWA Baker",
            "engine_version": VERSION,
            "updated_at": int(time.time()),
            "ready": checks.ready(found),
            "problems": [c["label"] + ": " + c["fix"] for c in found if c["required"] and not c["ok"]],
            "pending_requests": self.runner.pending(),
            "apps": [{"name": a["name"], "url": a["url"]} for a in baker.list_apps()],
        }
        _write_json(self.root / "status.json", status)

    def prune_results(self) -> None:
        cutoff = time.time() - RESULTS_KEEP_DAYS * 86400
        for path in (self.root / "results").glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass
