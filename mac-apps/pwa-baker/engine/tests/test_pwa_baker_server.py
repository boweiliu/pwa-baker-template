"""The local API the window uses, and the config migration from the old daemon."""

import json
import threading
import urllib.error
import urllib.request

import pytest
from conftest import ENV


@pytest.fixture
def api(engine_parts):
    from pwa_baker.server import Engine, make_server
    from pwa_baker.tunnel import Tunnel

    cfg, runner, dropbox = engine_parts
    engine = Engine(cfg, runner, dropbox, Tunnel(0, lambda _m: None))
    server = make_server(engine, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_address[1]

    def call(method, path, body=None, token=cfg.token, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        req.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    yield call
    server.shutdown()


def test_health_is_open_everything_else_needs_the_token(api):
    assert api("GET", "/health", token=None)[0] == 200
    assert api("GET", "/status", token=None)[0] == 401
    assert api("GET", "/status", token="wrong")[0] == 401
    assert api("POST", "/bake", {"url": "https://a.example/"}, token=None)[0] == 401


def test_bake_waits_and_returns_the_app(api):
    code, reply = api("POST", "/bake", {"url": "https://a.example/", "name": "A"})
    assert code == 200, reply
    assert reply["ok"] and reply["job"]["status"] == "done"
    assert reply["app_path"].endswith("/A.app")
    assert reply["job"]["source"] == "app"
    code, apps = api("GET", "/apps")
    assert [a["name"] for a in apps["apps"]] == ["A"]
    code, jobs = api("GET", "/jobs")
    assert jobs["jobs"][0]["id"] == reply["job"]["id"]
    assert api("GET", "/jobs/" + reply["job"]["id"])[1]["job"]["status"] == "done"


def test_bake_without_waiting_returns_a_job(api, engine_parts):
    cfg, runner, dropbox = engine_parts
    code, reply = api("POST", "/bake", {"url": "https://b.example/", "name": "B", "wait": False})
    assert code == 202 and reply["job"]["status"] in ("queued", "running", "done")
    assert runner.wait(reply["job"]["id"], 20)["status"] == "done"


def test_network_callers_cannot_name_files_on_the_mac(api, tmp_path):
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"\x89PNG")
    code, reply = api("POST", "/bake", {"url": "https://c.example/", "icon": str(secret)}, headers={"Cf-Ray": "abc"})
    assert code == 400 and reply["error"] == "bad_icon"
    # The window may.
    code, reply = api("POST", "/bake", {"url": "https://c.example/", "name": "C", "icon": str(secret)})
    assert code == 200, reply


def test_failures_carry_a_code_and_message(api):
    code, reply = api("POST", "/bake", {"url": "nope"})
    assert code == 400 and reply["error"] == "bad_url" and reply["message"]
    code, reply = api("POST", "/bake", {"url": "https://fails.example/"})
    assert code == 500 and reply["error"] == "installer_failed"


def test_settings_only_accept_known_switches(api):
    code, reply = api("POST", "/settings", {"desktop_alias": False, "token": "hijack", "port": 1})
    assert reply["settings"]["desktop_alias"] is False
    assert reply["settings"]["port"] == 7247
    code, status = api("GET", "/status")
    assert status["settings"]["desktop_alias"] is False
    assert {c["id"] for c in status["checks"]} >= {"chromium", "node", "template"}
    assert status["dropbox"]["exists"] is True


def test_old_daemon_config_carries_over(tmp_path):
    from pathlib import Path

    from pwa_baker import config

    path = Path(ENV["PWA_BAKER_CONFIG"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": "old-token", "installer": "/x/install.sh", "allow_dock": False}))
    cfg = config.Config(path)
    assert cfg.token == "old-token"
    assert cfg.get("add_to_dock") is False
    assert cfg.get("desktop_alias") is True
    assert oct(path.stat().st_mode & 0o777) == "0o600"
