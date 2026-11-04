"""The engine's HTTP API on 127.0.0.1, used by the app's window and (through the optional public
link) by agents that cannot use the shared folder.

Every route but /health needs `Authorization: Bearer <token>` (the token is in
~/.config/pwa-baker/config.json, which only this Mac user can read).

    GET  /health                 {ok, version}
    GET  /status                 setup checks, settings, shared folder, public link, queue
    GET  /apps                   baked apps
    GET  /jobs                   recent requests, newest first; /jobs/<id> for one
    POST /bake                   {url, name?, icon?, wait?}  wait (default true) blocks until done
    POST /uninstall              {name, wait?}
    POST /settings               {dropbox_enabled?, add_to_dock?, desktop_alias?, close_open_apps?}
    POST /tunnel                 {enabled}
"""

from __future__ import annotations

import json
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from . import VERSION, baker, checks, config
from .dropbox import DropBox
from .jobs import JobRunner
from .tunnel import Tunnel
from .validate import RequestError, parse_request

WAIT_SECONDS = 300
MAX_BODY = 64 * 1024


class Engine:
    """Everything the HTTP handler needs, in one place."""

    def __init__(self, cfg: "config.Config", runner: JobRunner, dropbox: DropBox, tunnel: Tunnel) -> None:
        self.cfg = cfg
        self.runner = runner
        self.dropbox = dropbox
        self.tunnel = tunnel

    def status(self) -> dict[str, Any]:
        found = checks.run_checks()
        return {
            "ok": True,
            "version": VERSION,
            "ready": checks.ready(found),
            "checks": found,
            "settings": self.cfg.public_settings(),
            "dropbox": {
                "path": str(self.dropbox.root),
                "exists": self.dropbox.root.is_dir(),
                "error": self.dropbox.last_error,
            },
            "tunnel": self.tunnel.state(),
            "pending": self.runner.pending(),
            "apps_dir": str(config.APPS_DIR),
        }


class Handler(BaseHTTPRequestHandler):
    engine: Engine
    server_version = "pwa-baker/" + VERSION

    def log_message(self, *args: Any) -> None:  # requests are logged as jobs instead
        pass

    def _send(self, code: int, obj: dict[str, Any]) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        header = self.headers.get("Authorization", "")
        return secrets.compare_digest(header.encode(), ("Bearer " + self.engine.cfg.token).encode())

    def _source(self) -> str:
        # Requests through the public link arrive with Cloudflare's headers; the window's do not.
        return "network" if self.headers.get("Cf-Connecting-Ip") or self.headers.get("Cf-Ray") else "app"

    def _body(self) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "bad Content-Length"
        if length > MAX_BODY:
            return None, "request too large"
        if length == 0:
            return {}, None
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            return None, "bad json"
        if not isinstance(data, dict):
            return None, "body must be a JSON object"
        return data, None

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            return self._send(200, {"ok": True, "version": VERSION, "app": "PWA Baker"})
        if not self._authed():
            return self._send(401, {"ok": False, "error": "unauthorized"})
        if path == "/status":
            return self._send(200, self.engine.status())
        if path == "/apps":
            return self._send(200, {"ok": True, "apps": baker.list_apps()})
        if path == "/list":  # the old daemon's name for /apps
            return self._send(200, {"ok": True, "apps": baker.list_apps()})
        if path == "/jobs":
            return self._send(200, {"ok": True, "jobs": self.engine.runner.recent()})
        if path.startswith("/jobs/"):
            job = self.engine.runner.get(path[len("/jobs/"):])
            return self._send(200 if job else 404, {"ok": bool(job), "job": job} if job else {"ok": False, "error": "not_found"})
        return self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        if not self._authed():
            return self._send(401, {"ok": False, "error": "unauthorized"})
        body, problem = self._body()
        if body is None:
            return self._send(400, {"ok": False, "error": "bad_request", "message": problem})
        if path in ("/bake", "/uninstall"):
            raw = dict(body, action=path[1:])
            try:
                action = parse_request(raw, None, config.APPS_DIR, allow_local_icon=self._source() == "app")
            except RequestError as exc:
                self.engine.runner.record_rejected(self._source(), raw, exc)
                return self._send(400, {"ok": False, "error": exc.code, "message": exc.message})
            job = self.engine.runner.submit(action, self._source(), raw)
            if body.get("wait", True) is False:
                return self._send(202, {"ok": True, "job": job})
            done = self.engine.runner.wait(job["id"], WAIT_SECONDS) or job
            ok = done["status"] == "done"
            reply = {"ok": ok, "job": done}
            if not ok:
                reply.update(error=done.get("error", "timeout"), message=done.get("message", "Still running"))
            reply.update(done.get("result") or {})
            return self._send(200 if ok else (202 if done["status"] in ("queued", "running") else 500), reply)
        if path == "/settings":
            settings = self.engine.cfg.update(body)
            return self._send(200, {"ok": True, "settings": settings})
        if path == "/tunnel":
            state = self.engine.tunnel.start() if body.get("enabled") else self.engine.tunnel.stop()
            return self._send(200, {"ok": True, "tunnel": state})
        return self._send(404, {"ok": False, "error": "not_found"})


def make_server(engine: Engine, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"engine": engine})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
