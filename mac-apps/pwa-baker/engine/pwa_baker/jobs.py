"""One queue for every request, run one at a time.

Bakes from the window, the shared folder and the network all land here, because two bakes at
once would fight over Chromium's database. Finished jobs are appended to
~/Library/Application Support/PWA Baker/history.jsonl with the raw request that started them.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from typing import Any, Callable, Optional

from . import baker, config
from .validate import RequestError

Listener = Callable[[dict[str, Any]], None]
HISTORY_KEEP = 200


def _now() -> float:
    return round(time.time(), 3)


class JobRunner:
    def __init__(self, cfg: "config.Config", log: Callable[[str], None]) -> None:
        self.cfg = cfg
        self.log = log
        self._jobs: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._events: dict[str, threading.Event] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._listeners: dict[str, Listener] = {}
        self.history_file = config.STATE_DIR / "history.jsonl"
        self._load_history()
        self._worker = threading.Thread(target=self._run, name="pwa-baker-jobs", daemon=True)
        self._worker.start()

    # --- history -------------------------------------------------------------------------

    def _load_history(self) -> None:
        if not self.history_file.exists():
            return
        lines = self.history_file.read_text(errors="replace").splitlines()[-HISTORY_KEEP:]
        for line in lines:
            try:
                job = json.loads(line)
            except ValueError:
                continue
            if isinstance(job, dict) and "id" in job:
                self._jobs[job["id"]] = job
                if job["id"] not in self._order:
                    self._order.append(job["id"])

    def _append_history(self, job: dict[str, Any]) -> None:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.history_file, "a") as handle:
            handle.write(json.dumps(job) + "\n")

    # --- submitting and reading ----------------------------------------------------------

    def submit(self, action: dict[str, Any], source: str, raw: Any, job_id: Optional[str] = None,
               listener: Optional[Listener] = None) -> dict[str, Any]:
        job_id = job_id or uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "source": source,
            "action": action["action"],
            "params": {k: v for k, v in action.items() if k != "action"},
            "request": raw,
            "status": "queued",
            "progress": "Waiting for its turn",
            "created_at": _now(),
        }
        with self._lock:
            if job_id in self._jobs and self._jobs[job_id]["status"] in ("queued", "running"):
                return dict(self._jobs[job_id])
            self._jobs[job_id] = job
            if job_id in self._order:
                self._order.remove(job_id)
            self._order.append(job_id)
            self._events[job_id] = threading.Event()
            if listener:
                self._listeners[job_id] = listener
        self.log("queued %s %s from %s" % (job["action"], json.dumps(job["params"]), source))
        self._notify(job_id)
        self._queue.put(job_id)
        return dict(job)

    def record_rejected(self, source: str, raw: Any, error: RequestError, job_id: Optional[str] = None) -> dict[str, Any]:
        """Keep a refused request in the activity list so the user can see what was asked."""
        job = {
            "id": job_id or uuid.uuid4().hex[:12],
            "source": source,
            "action": raw.get("action", "bake") if isinstance(raw, dict) else "unknown",
            "params": {},
            "request": raw,
            "status": "failed",
            "error": error.code,
            "message": error.message,
            "created_at": _now(),
            "finished_at": _now(),
        }
        with self._lock:
            self._jobs[job["id"]] = job
            self._order.append(job["id"])
        self._append_history(job)
        return dict(job)

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            ids = self._order[-limit:]
            return [dict(self._jobs[i]) for i in reversed(ids)]

    def pending(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j["status"] in ("queued", "running"))

    def wait(self, job_id: str, timeout: float) -> Optional[dict[str, Any]]:
        event = self._events.get(job_id)
        if event:
            event.wait(timeout)
        return self.get(job_id)

    # --- running -------------------------------------------------------------------------

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(fields)
        self._notify(job_id)

    def _notify(self, job_id: str) -> None:
        listener = self._listeners.get(job_id)
        job = self.get(job_id)
        if listener and job:
            try:
                listener(job)
            except Exception as exc:  # noqa: BLE001 - a listener failing must not stop the queue
                self.log("listener for %s failed: %r" % (job_id, exc))

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.get(job_id)
            if not job or job["status"] != "queued":
                continue
            self._update(job_id, status="running", started_at=_now(), progress="Starting")

            def progress(message: str, _id: str = job_id) -> None:
                self.log("%s: %s" % (_id, message))
                self._update(_id, progress=message)

            try:
                params = job["params"]
                if job["action"] == "bake":
                    result = baker.bake(params["url"], params.get("name"), params.get("icon"), self.cfg, progress)
                    message = "Baked %s" % app_stem(result.get("app_path", ""))
                elif job["action"] == "uninstall":
                    result = baker.uninstall(params["name"], progress)
                    message = "Removed %s" % params["name"]
                else:
                    raise RequestError("bad_action", "Unknown action %s" % job["action"])
                self._update(job_id, status="done", result=result, message=message, progress="", finished_at=_now())
            except RequestError as exc:
                details = getattr(exc, "details", None)
                self._update(job_id, status="failed", error=exc.code, message=exc.message, progress="",
                             finished_at=_now(), **({"result": details} if details else {}))
            except Exception as exc:  # noqa: BLE001 - report anything unexpected on the job itself
                self._update(job_id, status="failed", error="internal_error", message=repr(exc), progress="",
                             finished_at=_now())
            final = self.get(job_id)
            self.log("%s %s: %s" % (job_id, final["status"], final.get("message", "")))
            self._append_history(final)
            event = self._events.pop(job_id, None)
            if event:
                event.set()
            self._listeners.pop(job_id, None)


def app_stem(path: str) -> str:
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".app") else name
