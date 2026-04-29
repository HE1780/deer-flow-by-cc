"""Tests for app.gateway.identity.settings."""

import os
from unittest.mock import patch

from app.gateway.identity.settings import get_identity_settings


def test_defaults_flag_off_when_env_unset():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ENABLE_IDENTITY", None)
        get_identity_settings.cache_clear()
        settings = get_identity_settings()
    assert settings.enabled is False


def test_flag_on_when_truthy_env():
    for val in ["1", "true", "True", "TRUE", "yes", "on"]:
        with patch.dict(os.environ, {"ENABLE_IDENTITY": val}):
            get_identity_settings.cache_clear()
            assert get_identity_settings().enabled is True, f"ENABLE_IDENTITY={val!r} should enable"


def test_flag_off_when_falsy_env():
    for val in ["0", "false", "False", "no", "off", ""]:
        with patch.dict(os.environ, {"ENABLE_IDENTITY": val}):
            get_identity_settings.cache_clear()
            assert get_identity_settings().enabled is False, f"ENABLE_IDENTITY={val!r} should disable"


def test_database_url_default():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DEERFLOW_DATABASE_URL", None)
        get_identity_settings.cache_clear()
        assert get_identity_settings().database_url == "postgresql+asyncpg://deerflow:deerflow@localhost:5432/deerflow"


def test_database_url_from_env():
    with patch.dict(os.environ, {"DEERFLOW_DATABASE_URL": "postgresql+asyncpg://u:p@h:1/d"}):
        get_identity_settings.cache_clear()
        assert get_identity_settings().database_url == "postgresql+asyncpg://u:p@h:1/d"


def test_redis_url_default_and_override():
    get_identity_settings.cache_clear()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DEERFLOW_REDIS_URL", None)
        get_identity_settings.cache_clear()
        assert get_identity_settings().redis_url == "redis://localhost:6379/0"
    with patch.dict(os.environ, {"DEERFLOW_REDIS_URL": "redis://r:6379/5"}):
        get_identity_settings.cache_clear()
        assert get_identity_settings().redis_url == "redis://r:6379/5"


def test_bootstrap_admin_email_optional():
    get_identity_settings.cache_clear()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DEERFLOW_BOOTSTRAP_ADMIN_EMAIL", None)
        get_identity_settings.cache_clear()
        assert get_identity_settings().bootstrap_admin_email is None
    with patch.dict(os.environ, {"DEERFLOW_BOOTSTRAP_ADMIN_EMAIL": "admin@example.com"}):
        get_identity_settings.cache_clear()
        assert get_identity_settings().bootstrap_admin_email == "admin@example.com"


def test_settings_cached_between_calls():
    get_identity_settings.cache_clear()
    first = get_identity_settings()
    second = get_identity_settings()
    assert first is second


# --- M2 auth-related settings ---


def _auth_env_cleared() -> dict[str, str]:
    keys = [
        "DEERFLOW_JWT_PRIVATE_KEY",
        "DEERFLOW_JWT_PRIVATE_KEY_PATH",
        "DEERFLOW_JWT_PUBLIC_KEY_PATH",
        "DEERFLOW_JWT_ISSUER",
        "DEERFLOW_JWT_AUDIENCE",
        "DEERFLOW_ACCESS_TOKEN_TTL_SEC",
        "DEERFLOW_REFRESH_TOKEN_TTL_SEC",
        "DEERFLOW_COOKIE_NAME",
        "DEERFLOW_COOKIE_SECURE",
        "DEERFLOW_LOGIN_LOCKOUT_MAX_ATTEMPTS",
        "DEERFLOW_LOGIN_LOCKOUT_WINDOW_SEC",
        "DEERFLOW_LOGIN_LOCKOUT_BLOCK_SEC",
        "DEERFLOW_BCRYPT_COST",
        "DEERFLOW_INTERNAL_SIGNING_KEY",
    ]
    return {k: "" for k in keys}


def test_jwt_key_path_defaults_under_deerflow_home(tmp_path, monkeypatch):
    for k in _auth_env_cleared():
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEERFLOW_HOME", str(tmp_path))
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    # Defaults live under $DEERFLOW_HOME/_system
    assert s.jwt_private_key_path == str(tmp_path / "_system" / "jwt_private.pem")
    assert s.jwt_public_key_path == str(tmp_path / "_system" / "jwt_public.pem")
    assert s.jwt_private_key is None


def test_jwt_inline_key_overrides_path(monkeypatch):
    for k in _auth_env_cleared():
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEERFLOW_JWT_PRIVATE_KEY", "-----BEGIN RSA-----\nfoo\n-----END RSA-----")
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.jwt_private_key is not None and "BEGIN RSA" in s.jwt_private_key


def test_jwt_issuer_and_audience_defaults(monkeypatch):
    for k in _auth_env_cleared():
        monkeypatch.delenv(k, raising=False)
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.jwt_issuer == "deerflow"
    assert s.jwt_audience == "deerflow-api"


def test_jwt_issuer_and_audience_override(monkeypatch):
    monkeypatch.setenv("DEERFLOW_JWT_ISSUER", "custom-iss")
    monkeypatch.setenv("DEERFLOW_JWT_AUDIENCE", "custom-aud")
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.jwt_issuer == "custom-iss"
    assert s.jwt_audience == "custom-aud"


def test_token_ttl_defaults(monkeypatch):
    for k in _auth_env_cleared():
        monkeypatch.delenv(k, raising=False)
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.access_token_ttl_sec == 900
    assert s.refresh_token_ttl_sec == 604800


def test_token_ttl_override(monkeypatch):
    monkeypatch.setenv("DEERFLOW_ACCESS_TOKEN_TTL_SEC", "60")
    monkeypatch.setenv("DEERFLOW_REFRESH_TOKEN_TTL_SEC", "120")
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.access_token_ttl_sec == 60
    assert s.refresh_token_ttl_sec == 120


def test_cookie_defaults(monkeypatch):
    for k in _auth_env_cleared():
        monkeypatch.delenv(k, raising=False)
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.cookie_name == "deerflow_session"
    assert s.cookie_secure is True


def test_cookie_secure_override(monkeypatch):
    monkeypatch.setenv("DEERFLOW_COOKIE_SECURE", "false")
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.cookie_secure is False


def test_lockout_defaults(monkeypatch):
    for k in _auth_env_cleared():
        monkeypatch.delenv(k, raising=False)
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.login_lockout_max_attempts == 10
    assert s.login_lockout_window_sec == 300
    assert s.login_lockout_block_sec == 900


def test_lockout_overrides(monkeypatch):
    monkeypatch.setenv("DEERFLOW_LOGIN_LOCKOUT_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("DEERFLOW_LOGIN_LOCKOUT_WINDOW_SEC", "60")
    monkeypatch.setenv("DEERFLOW_LOGIN_LOCKOUT_BLOCK_SEC", "120")
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.login_lockout_max_attempts == 3
    assert s.login_lockout_window_sec == 60
    assert s.login_lockout_block_sec == 120


def test_bcrypt_cost_default_and_override(monkeypatch):
    for k in _auth_env_cleared():
        monkeypatch.delenv(k, raising=False)
    get_identity_settings.cache_clear()
    assert get_identity_settings().bcrypt_cost == 12
    monkeypatch.setenv("DEERFLOW_BCRYPT_COST", "4")
    get_identity_settings.cache_clear()
    assert get_identity_settings().bcrypt_cost == 4


def test_internal_signing_key_optional(monkeypatch):
    for k in _auth_env_cleared():
        monkeypatch.delenv(k, raising=False)
    get_identity_settings.cache_clear()
    assert get_identity_settings().internal_signing_key is None
    monkeypatch.setenv("DEERFLOW_INTERNAL_SIGNING_KEY", "abc123")
    get_identity_settings.cache_clear()
    assert get_identity_settings().internal_signing_key == "abc123"


# --- M4 storage root ---


def test_deer_flow_home_default_is_backend_dot_deer_flow(monkeypatch):
    """Default falls back to {backend_dir}/.deer-flow independent of CWD."""
    monkeypatch.delenv("DEER_FLOW_HOME", raising=False)
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    # Absolute, ends with backend/.deer-flow
    assert os.path.isabs(s.deer_flow_home)
    assert s.deer_flow_home.endswith(os.path.join("backend", ".deer-flow"))


def test_deer_flow_home_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.deer_flow_home == str(tmp_path)


# --- Registration code expires days ---


def test_registration_code_expires_days_default(monkeypatch):
    monkeypatch.delenv("REGISTRATION_CODE_EXPIRES_DAYS", raising=False)
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.registration_code_expires_days == 7


def test_registration_code_expires_days_clamped_low(monkeypatch):
    monkeypatch.setenv("REGISTRATION_CODE_EXPIRES_DAYS", "0")
    get_identity_settings.cache_clear()
    assert get_identity_settings().registration_code_expires_days == 7


def test_registration_code_expires_days_clamped_high(monkeypatch):
    monkeypatch.setenv("REGISTRATION_CODE_EXPIRES_DAYS", "999")
    get_identity_settings.cache_clear()
    assert get_identity_settings().registration_code_expires_days == 7


def test_registration_code_expires_days_in_range(monkeypatch):
    monkeypatch.setenv("REGISTRATION_CODE_EXPIRES_DAYS", "30")
    get_identity_settings.cache_clear()
    assert get_identity_settings().registration_code_expires_days == 30


def test_registration_code_expires_days_lower_bound(monkeypatch):
    monkeypatch.setenv("REGISTRATION_CODE_EXPIRES_DAYS", "1")
    get_identity_settings.cache_clear()
    assert get_identity_settings().registration_code_expires_days == 1


def test_registration_code_expires_days_upper_bound(monkeypatch):
    monkeypatch.setenv("REGISTRATION_CODE_EXPIRES_DAYS", "90")
    get_identity_settings.cache_clear()
    assert get_identity_settings().registration_code_expires_days == 90
