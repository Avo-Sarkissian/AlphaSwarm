"""One origin allow-list for HTTP and the WebSocket, and one trusted-host list."""

from __future__ import annotations

from pathlib import Path

import pytest

from alphaswarm.config import (
    DEFAULT_ALLOWED_ORIGINS,
    DEFAULT_TRUSTED_HOSTS,
    AppSettings,
    legacy_origin_settings,
)
from alphaswarm.web.origin_guard import is_allowed, normalized_allowlist


def _settings() -> AppSettings:
    return AppSettings(_env_file=None)  # type: ignore[call-arg]


def test_defaults_cover_vite_and_the_served_spa() -> None:
    settings = _settings()
    assert (
        settings.allowed_origins
        == DEFAULT_ALLOWED_ORIGINS
        == (
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        )
    )
    assert settings.trusted_hosts == DEFAULT_TRUSTED_HOSTS == ("localhost", "127.0.0.1", "[::1]")


def test_the_per_channel_settings_are_gone() -> None:
    assert "ws_allowed_origins" not in AppSettings.model_fields
    assert "http_allowed_origins" not in AppSettings.model_fields


def test_env_overrides_are_json_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHASWARM_ALLOWED_ORIGINS", '["http://lan-box.local:8000"]')
    monkeypatch.setenv("ALPHASWARM_TRUSTED_HOSTS", '["lan-box.local"]')
    settings = _settings()
    assert settings.allowed_origins == ("http://lan-box.local:8000",)
    assert settings.trusted_hosts == ("lan-box.local",)


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (None, True),  # header absent: a non-browser caller
        ("http://localhost:5173", True),
        ("HTTP://LOCALHOST:5173/", True),  # case and trailing slash fold
        ("http://127.0.0.1:8000/advisory", True),  # Referer-style URL folds to its origin
        ("http://localhost:9999", False),
        ("http://localhost", False),
        ("http://testserver", False),  # the request's own Host is never implied
        ("null", False),
        ("", False),
        ("http://localhost:5173.evil.example", False),
        ("http://localhost:5173@evil.example", False),
    ],
)
def test_is_allowed_is_the_one_policy(origin: str | None, expected: bool) -> None:
    assert is_allowed(origin, DEFAULT_ALLOWED_ORIGINS) is expected


@pytest.mark.parametrize("bad", ["localhost:5173", "*", "null", ""])
def test_invalid_allow_list_entries_fail_fast(bad: str) -> None:
    with pytest.raises(ValueError, match="not an origin"):
        normalized_allowlist([bad])


def test_legacy_origin_variables_are_reported(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# comment\nexport ALPHASWARM_WS_ALLOWED_ORIGINS=["http://lan-box.local:8000"]\nALPHASWARM_DEBUG=false\n',
        encoding="utf-8",
    )
    environ = {"ALPHASWARM_HTTP_ALLOWED_ORIGINS": "[]"}
    assert legacy_origin_settings(environ, env_file) == [
        "ALPHASWARM_HTTP_ALLOWED_ORIGINS",
        "ALPHASWARM_WS_ALLOWED_ORIGINS",
    ]
    assert legacy_origin_settings({}, tmp_path / "missing.env") == []
    assert legacy_origin_settings({}, None) == []


def test_create_app_warns_about_legacy_origin_variables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    web_test_settings: AppSettings,
) -> None:
    import alphaswarm.web.app as web_app

    events: list[tuple[str, dict[str, object]]] = []

    class _RecordingLog:
        def warning(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

        def info(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

        def debug(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

        def error(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

    monkeypatch.setattr(web_app, "log", _RecordingLog())
    # Keep the check hermetic: the class-level env_file points at the checkout's .env.
    monkeypatch.setitem(AppSettings.model_config, "env_file", tmp_path / "absent.env")
    monkeypatch.setenv("ALPHASWARM_WS_ALLOWED_ORIGINS", '["http://lan-box.local:8000"]')
    web_app.create_app(web_test_settings)
    assert (
        "legacy_origin_settings_ignored",
        {"names": ["ALPHASWARM_WS_ALLOWED_ORIGINS"], "use": "ALPHASWARM_ALLOWED_ORIGINS"},
    ) in events
