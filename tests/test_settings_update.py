"""Typed PUT /api/settings, and the settings routes on an unreadable stored config."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.config import (
    InferenceConfig,
    ProviderType,
    RoleConfig,
    load_inference_config,
    save_inference_config,
)
from alphaswarm.web.routes.settings import router as settings_router
from tests.support.web_app import make_route_app, route_test_settings

_STORED = InferenceConfig(
    orchestrator=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-orchestrator"),
    worker=RoleConfig(
        provider=ProviderType.ANTHROPIC, model="claude-test", api_key="sk-stored-key-1234"
    ),
    spend_cap_usd=Decimal("3"),
    allow_cloud_advisory=True,
)


@pytest.fixture(autouse=True)
def _keep_logging_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop create_app_state() from reconfiguring structlog for the session.

    Logger proxies cached earlier in the run hold the processor list that was
    configured then; a new configuration would leave later capture_logs tests
    blind to their events.
    """
    monkeypatch.setattr("alphaswarm.app.configure_logging", lambda **_: None)


def _app(tmp_path: Path) -> FastAPI:
    settings = route_test_settings(tmp_path)
    save_inference_config(_STORED, settings.inference_config_path)
    return make_route_app(settings_router, settings=settings)


def _saved(app: FastAPI) -> InferenceConfig:
    return load_inference_config(app.state.app_state.settings)


def test_explicit_null_role_is_422(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        r = client.put("/api/settings", json={"orchestrator": None})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "validation_error"
    assert detail["fields"][0]["loc"] == ["body", "orchestrator"]


def test_unknown_key_is_422_not_silently_ignored(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        r = client.put("/api/settings", json={"spend_cap": "5"})
    assert r.status_code == 422
    assert _saved(app).spend_cap_usd == Decimal("3")


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        ({"worker": {"api_kye": "sk-typo-secret-5555"}}, ["body", "worker", "api_kye"]),
        (
            {"limits": {"ollama": {"max_in_flght": 2}}},
            ["body", "limits", "ollama", "max_in_flght"],
        ),
        (
            {
                "pricing_overrides": {
                    "claude-test": {
                        "input_per_mtok": "1",
                        "output_per_mtok": "2",
                        "cached_per_mtok": "0.1",
                    }
                }
            },
            ["body", "pricing_overrides", "claude-test", "cached_per_mtok"],
        ),
    ],
    ids=["role", "limits", "pricing"],
)
def test_unknown_nested_key_is_422_and_nothing_is_saved(
    tmp_path: Path, body: dict[str, object], loc: list[str]
) -> None:
    """A typo such as 'api_kye' must not answer 200 while the old value stays in place."""
    app = _app(tmp_path)
    with TestClient(app) as client:
        before = _saved(app)
        r = client.put("/api/settings", json=body)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "validation_error"
    assert [f["loc"] for f in detail["fields"]] == [loc]
    assert "sk-typo-secret-5555" not in r.text
    assert _saved(app) == before


@pytest.mark.parametrize(("role", "field"), [("worker", "model"), ("orchestrator", "provider")])
def test_merge_error_location_names_the_role(tmp_path: Path, role: str, field: str) -> None:
    """A null that passes the body check but fails the merged RoleConfig says which role."""
    app = _app(tmp_path)
    with TestClient(app) as client:
        before = _saved(app)
        r = client.put("/api/settings", json={role: {field: None}})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "validation_error"
    assert [f["loc"] for f in detail["fields"]] == [["body", role, field]]
    assert _saved(app) == before


def test_omitted_keys_keep_stored_values(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        r = client.put("/api/settings", json={"spend_cap_usd": "5"})
        assert r.status_code == 200
    saved = _saved(app)
    assert saved.spend_cap_usd == Decimal("5")
    assert saved.worker.api_key == "sk-stored-key-1234"
    assert saved.orchestrator.model == "alphaswarm-orchestrator"
    assert saved.allow_cloud_advisory is True


def test_explicit_null_spend_cap_removes_the_cap(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        assert client.put("/api/settings", json={"spend_cap_usd": None}).status_code == 200
    assert _saved(app).spend_cap_usd is None


def test_partial_role_update_merges_and_keeps_the_key(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        r = client.put("/api/settings", json={"worker": {"model": "claude-other"}})
        assert r.status_code == 200
    saved = _saved(app)
    assert (saved.worker.model, saved.worker.api_key) == ("claude-other", "sk-stored-key-1234")


def test_validation_errors_never_echo_keys(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        r = client.put(
            "/api/settings",
            json={"worker": {"provider": "bad_provider", "api_key": "sk-new-secret-9876"}},
        )
    assert r.status_code == 422
    assert "sk-new-secret-9876" not in r.text


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/settings"), ("GET", "/api/settings/estimate"), ("PUT", "/api/settings")],
)
def test_stored_file_unreadable_is_422_naming_a_fix_outside_settings(
    tmp_path: Path, method: str, path: str
) -> None:
    """Settings can neither load nor save over an invalid file, so the fix is the file."""
    app = _app(tmp_path)
    (tmp_path / "inference.json").write_text("{not json", encoding="utf-8")
    with TestClient(app) as client:
        r = client.request(method, path, json={"spend_cap_usd": "5"} if method == "PUT" else None)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "inference_config_invalid"
    assert "ALPHASWARM_INFERENCE_CONFIG_PATH" in detail["message"]
    assert "fix it in Settings" not in detail["message"]
    assert str(tmp_path) not in r.text
    assert ".secrets" not in r.text
