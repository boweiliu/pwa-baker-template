
import pytest
from pwa_baker.validate import (
    RequestError,
    clean_icon,
    clean_job_id,
    clean_name,
    clean_url,
    parse_request,
    resolve_app_path,
)


def code_of(fn, *args, **kwargs):
    with pytest.raises(RequestError) as info:
        fn(*args, **kwargs)
    return info.value.code


def test_urls_must_be_http_with_a_host():
    assert clean_url(" https://example.com ") == "https://example.com/"
    assert clean_url("http://localhost:8080/app?x=1") == "http://localhost:8080/app?x=1"
    assert code_of(clean_url, "file:///etc/passwd") == "bad_url"
    assert code_of(clean_url, "javascript:alert(1)") == "bad_url"
    assert code_of(clean_url, "https://") == "bad_url"
    assert code_of(clean_url, "") == "url_required"
    assert code_of(clean_url, None) == "url_required"


def test_names_cannot_leave_the_apps_folder(tmp_path):
    assert clean_name("  My App ") == "My App"
    assert clean_name("a/b:c") == "a-b-c"
    assert code_of(clean_name, "..") == "bad_name"
    assert code_of(clean_name, "...") == "bad_name"
    assert clean_name(None) is None and clean_name("  ") is None
    assert len(clean_name("x" * 200)) == 60
    apps = tmp_path / "apps"
    apps.mkdir()
    assert resolve_app_path(apps, "../../etc").parent == apps.resolve()
    assert resolve_app_path(apps, "Notes").name == "Notes.app"
    assert code_of(resolve_app_path, apps, None) == "name_required"


def test_icons_are_addresses_or_files_inside_the_shared_folder(tmp_path):
    box = tmp_path / "box"
    (box / "icons").mkdir(parents=True)
    (box / "icons" / "a.png").write_bytes(b"\x89PNG")
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"\x89PNG")
    assert clean_icon("https://x.example/i.png", box) == "https://x.example/i.png"
    assert clean_icon("icons/a.png", box) == str((box / "icons" / "a.png").resolve())
    assert code_of(clean_icon, "../secret.png", box) == "bad_icon"
    assert code_of(clean_icon, str(secret), box) == "bad_icon"
    assert code_of(clean_icon, "icons/missing.png", box) == "icon_missing"
    assert code_of(clean_icon, "ftp://x/i.png", box) == "bad_icon"
    assert code_of(clean_icon, "icons/a.png", None) == "bad_icon"
    # Only the app's own window may name any file on the Mac.
    assert clean_icon(str(secret), None, allow_local=True) == str(secret)


def test_request_ids_are_plain_file_names():
    assert clean_job_id("abc-123_x.y") == "abc-123_x.y"
    assert code_of(clean_job_id, "../x") == "bad_request_id"
    assert code_of(clean_job_id, "") == "bad_request_id"


def test_parse_request_actions(tmp_path):
    apps = tmp_path / "apps"
    apps.mkdir()
    assert parse_request({"url": "https://a.example"}, None, apps) == {
        "action": "bake", "url": "https://a.example/", "name": None, "icon": None,
    }
    assert parse_request({"action": "uninstall", "name": "Notes"}, None, apps) == {"action": "uninstall", "name": "Notes"}
    assert code_of(parse_request, {"action": "format-disk"}, None, apps) == "bad_action"
    assert code_of(parse_request, ["https://a.example"], None, apps) == "bad_request"
