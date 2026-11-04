"""Checks on what a request asks for, before anything touches the Mac.

Requests come from the app's window, from agents through the shared folder, and from agents
over the network, so everything here treats its input as untrusted: only http(s) addresses,
app names that stay inside the apps folder, and icons that are either an http(s) address or
a file inside the shared folder.
"""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import Any, Optional

MAX_NAME = 60
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


class RequestError(ValueError):
    """A request the engine refuses; `code` is a short stable string agents can branch on."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def clean_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RequestError("url_required", "Give the web address to turn into an app.")
    url = value.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RequestError("bad_url", "The address must start with http:// or https://.")
    if not parsed.path:
        url = urllib.parse.urlunparse(parsed._replace(path="/"))
    return url


def clean_name(value: Any) -> Optional[str]:
    """An app name that is safe as a file name in the apps folder, or None to let the site decide."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise RequestError("bad_name", "The app name must be text.")
    name = "".join(ch for ch in value if ch.isprintable())
    name = name.replace("/", "-").replace(":", "-").strip().strip(".").strip()
    if not name:
        raise RequestError("bad_name", "That app name has no usable characters.")
    return name[:MAX_NAME].strip()


def resolve_app_path(apps_dir: Path, name: Any) -> Path:
    """The .app inside apps_dir for a name; refuses anything that would land elsewhere."""
    cleaned = clean_name(name)
    if cleaned is None:
        raise RequestError("name_required", "Say which app by its name.")
    path = (apps_dir / (cleaned + ".app")).resolve()
    if path.parent != apps_dir.resolve():
        raise RequestError("bad_name", "That name points outside the apps folder.")
    return path


def clean_icon(value: Any, dropbox_dir: Optional[Path], allow_local: bool = False) -> Optional[str]:
    """An http(s) icon address, or the absolute path of an icon file inside the shared folder.

    allow_local admits any picture file on this Mac; only the app's own window gets that.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise RequestError("bad_icon", "The icon must be an address or a file name.")
    icon = value.strip()
    parsed = urllib.parse.urlparse(icon)
    if parsed.scheme in ("http", "https") and parsed.hostname:
        return icon
    if parsed.scheme:
        raise RequestError("bad_icon", "Icon addresses must start with http:// or https://.")
    if allow_local and Path(icon).expanduser().is_absolute():
        local = Path(icon).expanduser()
        if not local.is_file():
            raise RequestError("icon_missing", "No picture file at %s." % icon)
        return str(local)
    if dropbox_dir is None:
        raise RequestError("bad_icon", "Icon files are only accepted from the shared folder.")
    root = dropbox_dir.resolve()
    path = (root / icon).resolve()
    if root not in path.parents:
        raise RequestError("bad_icon", "Icon files must be inside the shared folder (for example icons/my-app.png).")
    if not path.is_file():
        raise RequestError("icon_missing", "No icon file at %s in the shared folder (it may still be syncing)." % icon)
    return str(path)


def clean_job_id(value: str) -> str:
    if not _JOB_ID.match(value):
        raise RequestError("bad_request_id", "Request file names may use letters, digits, '-', '_' and '.'.")
    return value


def parse_request(body: Any, dropbox_dir: Optional[Path], apps_dir: Path, allow_local_icon: bool = False) -> dict[str, Any]:
    """Turn a raw request into the action the job runner performs."""
    if not isinstance(body, dict):
        raise RequestError("bad_request", "A request is a JSON object.")
    action = body.get("action", "bake")
    if action == "bake":
        return {
            "action": "bake",
            "url": clean_url(body.get("url")),
            "name": clean_name(body.get("name")),
            "icon": clean_icon(body.get("icon"), dropbox_dir, allow_local_icon),
        }
    if action == "uninstall":
        path = resolve_app_path(apps_dir, body.get("name"))
        return {"action": "uninstall", "name": path.stem}
    raise RequestError("bad_action", "Unknown action %r; use \"bake\" or \"uninstall\"." % (action,))
