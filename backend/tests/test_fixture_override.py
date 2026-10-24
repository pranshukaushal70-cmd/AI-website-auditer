"""Security-hardening phase 2: the test-only local-target override cannot be enabled through the environment."""

import time

import pytest
from conftest import FixtureSite, local_test_client, make_settings

from brand_platform.config import Settings
from brand_platform.db import Database
from brand_platform.main import create_app
from brand_platform.runner import JobManager

UNSAFE_VARIABLES = ("BRAND_PLATFORM_LOCAL_FIXTURE_PORT", "BRAND_AUDIT_LOCAL_FIXTURE")


@pytest.fixture()
def site():
    with FixtureSite() as s:
        yield s


@pytest.fixture()
def unsafe_server_env(monkeypatch, site):
    """Both legacy override variables set in the *server's* environment, pointing at a live local site."""
    for name in UNSAFE_VARIABLES:
        monkeypatch.setenv(name, str(site.port))
    return site


def test_environment_variable_does_not_enable_local_targets(unsafe_server_env):
    assert Settings().local_fixture_port is None


def test_api_refuses_local_target_even_with_unsafe_environment(unsafe_server_env, tmp_path):
    site = unsafe_server_env
    with local_test_client(create_app(make_settings(tmp_path))) as client:
        r = client.post("/api/audits", json={"url": site.base + "/"})
        assert r.status_code == 422 and r.json()["error"]["code"] in ("port_not_allowed", "non_public_address")
        assert client.get("/api/audits").json()["total"] == 0
    assert site.requests == []


def _job_manager(tmp_path, **overrides):
    settings = make_settings(tmp_path, **overrides)
    return JobManager(settings, Database(settings.db_path)), settings


def test_child_environment_never_inherits_unsafe_overrides(unsafe_server_env, tmp_path):
    jobs, _ = _job_manager(tmp_path)
    try:
        env = jobs._child_env()
    finally:
        jobs.shutdown()
    for name in UNSAFE_VARIABLES:
        assert name not in env


def test_only_the_code_level_setting_reaches_the_child(monkeypatch, tmp_path):
    for name in UNSAFE_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    jobs, _ = _job_manager(tmp_path, local_fixture_port=8123)
    try:
        env = jobs._child_env()
    finally:
        jobs.shutdown()
    assert env["BRAND_AUDIT_LOCAL_FIXTURE"] == "8123" and "BRAND_PLATFORM_LOCAL_FIXTURE_PORT" not in env


def test_spawned_engine_cannot_use_the_override_even_if_admission_were_bypassed(unsafe_server_env, tmp_path):
    """Defence in depth: hand the runner a loopback URL directly (skipping API URL validation) while the
    server environment carries the override. The real engine child must refuse to fetch anything."""
    site = unsafe_server_env
    jobs, settings = _job_manager(tmp_path)
    try:
        audit_id = jobs.submit(site.base + "/", "127.0.0.1", 2)
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            audit = jobs.db.get_audit(audit_id)
            if audit["status"] not in ("queued", "running"):
                break
            time.sleep(0.5)
    finally:
        jobs.shutdown()
    assert audit["status"] in ("partial", "failed"), audit
    assert site.requests == [], f"the engine fetched {site.requests} from a loopback target"
