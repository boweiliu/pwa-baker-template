"""The shared folder: what an agent writes, and what it reads back."""

import json
import os
import time
from pathlib import Path

from conftest import ENV, installer_args, read_json


def wait_done(runner, job_id, timeout=20):
    job = runner.wait(job_id, timeout)
    assert job is not None
    assert job["status"] in ("done", "failed"), job
    return job


def test_a_dropped_request_bakes_and_reports_back(engine_parts, dropbox_dir):
    cfg, runner, dropbox = engine_parts
    (dropbox_dir / "requests" / "req-1.json").write_text(json.dumps({"url": "https://notes.example", "name": "Notes"}))
    assert dropbox.scan() == 1
    assert not (dropbox_dir / "requests" / "req-1.json").exists()
    job = wait_done(runner, "req-1")
    assert job["status"] == "done", job
    result = read_json(dropbox_dir / "results" / "req-1.json")
    assert result["status"] == "done"
    assert result["source"] == "folder"
    assert result["request"] == {"url": "https://notes.example", "name": "Notes"}
    assert result["result"]["app_path"] == str(Path(ENV["PWA_BAKER_APPS_DIR"]) / "Notes.app")
    assert result["result"]["app_id"] == "abcdefghijklmnopabcdefghijklmnop"
    assert installer_args()[0] == "https://notes.example/"
    assert installer_args()[installer_args().index("--name") + 1] == "Notes"
    # Desktop alias is a symlink to the new app.
    link = Path(ENV["PWA_BAKER_DESKTOP_DIR"]) / "Notes.app"
    assert link.is_symlink() and os.readlink(link) == result["result"]["app_path"]
    status = read_json(dropbox_dir / "status.json")
    assert status["apps"] == [{"name": "Notes", "url": "https://notes.example/"}]
    assert abs(status["updated_at"] - time.time()) < 60
    # The run is kept in the history file with its raw request.
    history = [json.loads(line) for line in runner.history_file.read_text().splitlines()]
    assert history[-1]["id"] == "req-1" and history[-1]["request"]["name"] == "Notes"


def test_an_icon_put_in_the_folder_reaches_the_installer(engine_parts, dropbox_dir):
    cfg, runner, dropbox = engine_parts
    (dropbox_dir / "icons" / "n.png").write_bytes(b"\x89PNG fake")
    (dropbox_dir / "requests" / "req-2.json").write_text(json.dumps({"url": "https://n.example/", "name": "N", "icon": "icons/n.png"}))
    dropbox.scan()
    assert wait_done(runner, "req-2")["status"] == "done"
    args = installer_args()
    assert args[args.index("--icon") + 1] == str((dropbox_dir / "icons" / "n.png").resolve())


def test_a_request_waits_for_its_icon_to_finish_syncing(engine_parts, dropbox_dir):
    cfg, runner, dropbox = engine_parts
    req = dropbox_dir / "requests" / "req-3.json"
    req.write_text(json.dumps({"url": "https://n.example/", "icon": "icons/late.png"}))
    assert dropbox.scan() == 0 and req.exists()
    old = time.time() - 120
    os.utime(req, (old, old))
    assert dropbox.scan() == 1
    result = read_json(dropbox_dir / "results" / "req-3.json")
    assert result["status"] == "failed" and result["error"] == "icon_missing"


def test_bad_requests_are_answered_not_dropped(engine_parts, dropbox_dir):
    cfg, runner, dropbox = engine_parts
    (dropbox_dir / "requests" / "bad-url.json").write_text(json.dumps({"url": "file:///etc/passwd"}))
    (dropbox_dir / "requests" / "outside.json").write_text(json.dumps({"url": "https://a.example/", "icon": "../../.ssh/id_rsa"}))
    dropbox.scan()
    assert read_json(dropbox_dir / "results" / "bad-url.json")["error"] == "bad_url"
    assert read_json(dropbox_dir / "results" / "outside.json")["error"] == "bad_icon"
    assert installer_args() == []
    assert {j["id"] for j in runner.recent()} >= {"bad-url", "outside"}


def test_half_written_files_are_left_until_the_sync_finishes(engine_parts, dropbox_dir):
    cfg, runner, dropbox = engine_parts
    partial = dropbox_dir / "requests" / "partial.json"
    partial.write_text('{"url": "https://a.exa')
    (dropbox_dir / "requests" / "x.json.tmp").write_text("{}")
    assert dropbox.scan() == 0 and partial.exists()
    old = time.time() - 60
    os.utime(partial, (old, old))
    assert dropbox.scan() == 1
    assert read_json(dropbox_dir / "results" / "partial.json")["error"] == "bad_json"
    assert (dropbox_dir / "requests" / "x.json.tmp").exists()


def test_installer_failure_is_reported_with_its_output(engine_parts, dropbox_dir):
    cfg, runner, dropbox = engine_parts
    (dropbox_dir / "requests" / "boom.json").write_text(json.dumps({"url": "https://fails.example/"}))
    dropbox.scan()
    job = wait_done(runner, "boom")
    assert job["status"] == "failed" and job["error"] == "installer_failed"
    assert "proto synthesis failed" in job["message"]
    assert "proto synthesis failed" in read_json(dropbox_dir / "results" / "boom.json")["result"]["log_tail"]


def test_uninstall_through_the_folder(engine_parts, dropbox_dir):
    cfg, runner, dropbox = engine_parts
    (dropbox_dir / "requests" / "a.json").write_text(json.dumps({"url": "https://a.example/", "name": "Gone Soon"}))
    dropbox.scan()
    wait_done(runner, "a")
    app = Path(ENV["PWA_BAKER_APPS_DIR"]) / "Gone Soon.app"
    assert app.is_dir()
    (dropbox_dir / "requests" / "b.json").write_text(json.dumps({"action": "uninstall", "name": "Gone Soon"}))
    dropbox.scan()
    job = wait_done(runner, "b")
    assert job["status"] == "done", job
    assert not app.exists()
    assert not (Path(ENV["PWA_BAKER_DESKTOP_DIR"]) / "Gone Soon.app").is_symlink()


def test_uninstall_refuses_things_that_are_not_web_apps(engine_parts, dropbox_dir):
    cfg, runner, dropbox = engine_parts
    real = Path(ENV["PWA_BAKER_APPS_DIR"]) / "Real.app" / "Contents"
    real.mkdir(parents=True)
    (real / "Info.plist").write_text('<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleName</key><string>Real</string></dict></plist>')
    (dropbox_dir / "requests" / "c.json").write_text(json.dumps({"action": "uninstall", "name": "Real"}))
    dropbox.scan()
    job = wait_done(runner, "c")
    assert job["error"] == "not_a_web_app"
    assert real.is_dir()


def test_chromium_missing_is_a_clear_failure(engine_parts, dropbox_dir):
    cfg, runner, dropbox = engine_parts
    os.rmdir(ENV["PWA_BAKER_CHROMIUM_APP"])
    (dropbox_dir / "requests" / "d.json").write_text(json.dumps({"url": "https://a.example/"}))
    dropbox.scan()
    job = wait_done(runner, "d")
    assert job["error"] == "chromium_missing"


def test_first_bake_on_a_fresh_chromium_sets_up_its_profile(engine_parts, dropbox_dir, monkeypatch):
    from pwa_baker import baker

    calls = []
    monkeypatch.setattr(baker, "profile_ready", lambda: bool(calls))
    monkeypatch.setattr(baker, "prepare_profile", lambda progress: calls.append(1) or True)
    cfg, runner, dropbox = engine_parts
    (dropbox_dir / "requests" / "p.json").write_text(json.dumps({"url": "https://p.example/"}))
    dropbox.scan()
    job = wait_done(runner, "p")
    assert job["status"] == "done" and job["result"]["prepared_profile"] is True
    assert calls == [1]
