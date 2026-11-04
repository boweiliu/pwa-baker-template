"""The optional public link: a Cloudflare quick tunnel to the local API.

Off by default. The shared folder is the normal way in; this is for an agent that cannot use
it. The link changes every time it is turned on; the token does not.
"""

from __future__ import annotations

import re
import subprocess
import threading
from typing import Any, Callable, Optional

from .baker import sub_env, which

_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class Tunnel:
    def __init__(self, port: int, log: Callable[[str], None]) -> None:
        self.port = port
        self.log = log
        self._proc: Optional[subprocess.Popen] = None
        self.url: Optional[str] = None
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    def state(self) -> dict[str, Any]:
        running = self._proc is not None and self._proc.poll() is None
        return {
            "available": which("cloudflared") is not None,
            "running": running,
            "url": self.url if running else None,
            "error": self.error,
        }

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return self.state()
            exe = which("cloudflared")
            if not exe:
                self.error = "cloudflared is not installed (brew install cloudflared)"
                return self.state()
            self.url, self.error = None, None
            self._proc = subprocess.Popen(
                [exe, "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:%d" % self.port],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=sub_env(),
            )
            threading.Thread(target=self._read, args=(self._proc,), daemon=True).start()
        return self.state()

    def _read(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            match = _URL.search(line)
            if match and not self.url:
                self.url = match.group(0)
                self.log("public link up: %s" % self.url)
        code = proc.wait()
        if proc is self._proc and code not in (0, -15):
            self.error = "cloudflared stopped (exit %s)" % code
            self.log(self.error)

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc, self.url, self.error = None, None, None
        return self.state()
