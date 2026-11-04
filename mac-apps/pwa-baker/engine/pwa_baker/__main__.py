"""Run the engine: `python3 -m pwa_baker serve [--port N] [--parent-pid PID]`.

The PWA Baker app starts this itself and passes its own pid, so the engine exits when the app
does instead of lingering on the port.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time

from . import VERSION, config
from .dropbox import DropBox
from .jobs import JobRunner
from .server import Engine, make_server
from .tunnel import Tunnel


def make_logger():
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = config.LOG_DIR / "engine.log"
    lock = threading.Lock()

    def log(message: str) -> None:
        line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message)
        with lock:
            with open(path, "a") as handle:
                handle.write(line + "\n")
        print(line, file=sys.stderr, flush=True)

    return log


def _watch_parent(pid: int, log) -> None:
    while True:
        time.sleep(2)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            log("app (pid %d) is gone; stopping" % pid)
            os._exit(0)
        except PermissionError:
            pass


def serve(args: argparse.Namespace) -> int:
    log = make_logger()
    cfg = config.Config()
    port = args.port or int(cfg.get("port"))
    runner = JobRunner(cfg, log)
    dropbox = DropBox(cfg, runner, log)
    tunnel = Tunnel(port, log)
    engine = Engine(cfg, runner, dropbox, tunnel)
    try:
        server = make_server(engine, args.host, port)
    except OSError as exc:
        log("cannot listen on %s:%d: %s" % (args.host, port, exc))
        return 2
    if cfg.get("dropbox_enabled"):
        try:
            dropbox.prepare()
        except OSError as exc:
            log("cannot create the shared folder %s: %s" % (dropbox.root, exc))
    dropbox.start()
    if args.parent_pid:
        threading.Thread(target=_watch_parent, args=(args.parent_pid, log), daemon=True).start()
    log("PWA Baker engine %s on http://%s:%d, shared folder %s" % (VERSION, args.host, port, dropbox.root))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        tunnel.stop()
        dropbox.stop()
        log("stopped")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pwa_baker")
    sub = parser.add_subparsers(dest="command")
    p_serve = sub.add_parser("serve", help="run the engine")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--parent-pid", type=int, default=0)
    sub.add_parser("version")
    args = parser.parse_args(argv)
    if args.command == "serve":
        return serve(args)
    if args.command == "version":
        print(VERSION)
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
