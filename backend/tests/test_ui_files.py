"""The built-UI file route (security phase 7, H1): files are served only from frontend/dist, and a path that could
escape it is refused before any filesystem call (on Windows a UNC path made the server open an SMB connection)."""

import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from conftest import local_test_client, make_settings

from brand_platform.main import create_app, ui_file

INDEX = "<!doctype html><title>UI</title><div id=root></div>"
APP_JS = "console.log('app');"


@pytest.fixture()
def site(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "index-B-vUFE-P.js").write_text(APP_JS, encoding="utf-8")
    (dist / "assets" / "index-Dt2g.css").write_text("body{}", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")  # outside dist
    with local_test_client(create_app(make_settings(tmp_path, frontend_dist=dist))) as client:  # runs startup
        yield client, dist, tmp_path


def raw_get(client, raw_path: str):
    """Send the path byte-for-byte. The HTTP client would otherwise read '//host/...' as a host and rewrite it."""
    return client.get(httpx.URL("http://127.0.0.1/").copy_with(raw_path=raw_path.encode("ascii")))


def test_assets_are_served_from_dist(site):
    client, _, _ = site
    r = client.get("/assets/index-B-vUFE-P.js")
    assert r.status_code == 200 and r.text == APP_JS and "javascript" in r.headers["content-type"]
    assert client.get("/assets/index-Dt2g.css").headers["content-type"].startswith("text/css")
    assert client.get("/favicon.svg").text == "<svg/>"


@pytest.mark.parametrize("path", ["/", "/dashboard", "/audits/0123456789abcdef0123456789abcdef", "/history",
                                  "/compare?base=a&target=b", "/assets", "/assets/missing-file.js"])
def test_client_routes_and_missing_files_fall_back_to_index(site, path):
    client, _, _ = site
    r = client.get(path)
    assert r.status_code == 200 and r.text == INDEX


def test_api_routes_are_unaffected(site):
    client, _, _ = site
    assert client.get("/api/health").status_code == 200
    r = client.get("/api/no-such-endpoint")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


UNSAFE = [
    # traversal (encoded so the HTTP client cannot normalise it away)
    "/%2E%2E/secret.txt", "/assets/%2E%2E/%2E%2E/secret.txt", "/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt",
    "/.%2E/secret.txt", "/assets/./index-B-vUFE-P.js".replace("/./", "/%2E/"),
    # backslash separators and Windows-style paths
    "/..%5Csecret.txt", "/assets%5C..%5C..%5Csecret.txt", "/assets%5Cindex-B-vUFE-P.js",
    "/C:/Windows/win.ini", "/C%3A%5CWindows%5Cwin.ini", "/c:secret.txt", "/index.html::$DATA", "/index.html%3A%3A%24DATA",
    # absolute paths
    "/%2Fetc%2Fpasswd", "//etc/passwd", "///etc/passwd",
    # UNC paths
    "/%5C%5Cattacker.example%5Cshare%5Cx.png", "/%2F%2Fattacker.example/share/x", "///attacker.example/share/x.png",
    "/%5C%5C%3F%5CUNC%5Cattacker.example%5Cshare", "/%5C%5C.%5Cpipe%5Cx",
    # device names, trailing dots and spaces, NUL, hidden files
    "/CON", "/assets/nul.js", "/aux", "/COM1.txt", "/index.html.", "/index.html%20", "/index.html%00.js", "/.env",
    "/assets/.hidden",
]


@pytest.mark.parametrize("path", UNSAFE)
def test_unsafe_paths_are_refused(site, path):
    client, _, _ = site
    r = raw_get(client, path)
    assert r.status_code == 404, (path, r.status_code, r.text[:80])
    assert "TOP-SECRET" not in r.text and INDEX not in r.text


@pytest.mark.parametrize("path", ["/%5C%5Cattacker.example%5Cshare%5Cx.png", "/%2F%2Fattacker.example/share/x",
                                  "///attacker.example/share/x.png", "/%5C%5C%3F%5CUNC%5Cattacker.example%5Cshare"])
def test_unc_paths_never_reach_the_filesystem(site, path):
    """The vulnerability: resolving or stat-ing a UNC path makes Windows contact that host. Intercept every pathlib
    filesystem entry point and fail if any receives a path naming the attacker's host."""
    client, _, _ = site
    touched = []
    originals = {name: getattr(Path, name) for name in ("resolve", "stat", "is_file", "exists", "lstat")}

    def guard(name):
        def wrapper(self, *args, **kwargs):
            if "attacker.example" in str(self):
                touched.append((name, str(self)))
                raise AssertionError(f"filesystem call {name}({self})")
            return originals[name](self, *args, **kwargs)
        return wrapper
    with patch.multiple(Path, **{name: guard(name) for name in originals}):
        r = raw_get(client, path)
    assert touched == [] and r.status_code == 404


def test_symlinked_file_out_of_dist_is_refused(site):
    """May skip only on Windows, where creating a symlink needs a privilege; elsewhere a failure fails the test, so
    CI on Linux always exercises it."""
    client, dist, tmp_path = site
    try:
        os.symlink(tmp_path / "secret.txt", dist / "leak.txt")
    except OSError as exc:
        if os.name != "nt":
            raise
        pytest.skip(f"this Windows account cannot create symlinks: {exc}")
    r = client.get("/leak.txt")
    assert r.status_code == 404 and "TOP-SECRET" not in r.text


def test_linked_directory_out_of_dist_is_refused(site):
    """Never skipped: a directory symlink on POSIX, and on Windows a directory junction (no privilege needed)."""
    client, dist, tmp_path = site
    outside = tmp_path / "outside-dist"
    outside.mkdir()
    (outside / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
    link = dist / "linked"
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(outside), str(link))
    else:
        os.symlink(outside, link, target_is_directory=True)
    try:
        assert (link / "secret.txt").read_text(encoding="utf-8") == "TOP-SECRET"  # the link really leads outside
        r = client.get("/linked/secret.txt")
        assert r.status_code == 404 and "TOP-SECRET" not in r.text
    finally:
        if os.name == "nt":
            os.rmdir(link)  # removes the junction itself, never its target
        else:
            link.unlink()


def test_ui_file_decides_from_the_string_alone(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "a.js").write_text("x", encoding="utf-8")
    dist = dist.resolve()
    assert ui_file(dist, "") == ("fallback", None)
    assert ui_file(dist, "assets/a.js") == ("file", dist / "assets" / "a.js")
    assert ui_file(dist, "audits/abc") == ("fallback", None)
    for unsafe in ("..", "../x", "a/../b", "a//b", "/abs", "\\\\host\\share", "C:x", "a\\b", "x\x00", "a.", ".a", "nul",
                   "Nul.txt", "a" * 1025):
        assert ui_file(dist, unsafe) == ("reject", None), unsafe
