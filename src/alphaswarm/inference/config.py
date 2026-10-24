"""Runtime-mutable inference configuration, persisted as .secrets/inference.json.

The file can hold cloud API keys in cleartext: it is written owner-only (CWE-276)
and its contents are never logged (docs/DECISIONS.md#adr-local-first-inference).
"""

from __future__ import annotations

import os
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from alphaswarm.errors import InferenceConfigFileError
from alphaswarm.settings import PROJECT_ROOT, AppSettings

logger = structlog.get_logger(component="inference_config")


# ---------------------------------------------------------------------------
# Inference provider configuration (runtime-mutable, persisted as JSON)
# ---------------------------------------------------------------------------


class ProviderType(StrEnum):
    """Which inference backend to use for a role.

    Distinct from ProviderRole (which slot — orchestrator/worker).
    This is a config-layer concept: which backend implementation to use.
    """

    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"


class RoleConfig(BaseModel):
    """Per-role inference backend configuration."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderType
    model: str
    base_url: str | None = None
    api_key: str | None = None


class ProviderLimits(BaseModel):
    """Rate and concurrency limits for a provider backend."""

    # extra="forbid" turns a typo into an error instead of a silent default; the
    # lower bounds stop a zero from dividing by zero or blocking forever.
    model_config = ConfigDict(extra="forbid")

    requests_per_min: int | None = Field(default=None, ge=1)
    tokens_per_min: int | None = Field(default=None, ge=1)
    max_in_flight: int = Field(default=24, ge=1)  # concurrency cap for the cloud path
    # HTTP retry budget for 408/409/429/5xx on both cloud paths. The
    # constructor default is 3; free tiers (e.g. NVIDIA NIM) return 429 with no
    # Retry-After and a bursty leaky-bucket refill, so a higher value lets a
    # serialized worker ride out rate-limit windows instead of dropping the
    # agent. Empirically, max_in_flight=1 + requests_per_min=40 + max_retries=8
    # cut worker failures from ~15% to ~2% on the NVIDIA free tier.
    max_retries: int = Field(default=3, ge=0)
    # Tokens reserved against tokens_per_min before each call, reconciled to the
    # real count afterwards. Lower it toward your real prompt size when TPM
    # throttles too early (docs/DECISIONS.md#adr-cloud-retry).
    avg_tokens_per_call: int = Field(default=1500, ge=1)


class ModelPrice(BaseModel):
    """USD pricing for a specific model (cost-accounting / budget enforcement)."""

    model_config = ConfigDict(extra="forbid")

    input_per_mtok: Decimal  # USD per 1M input tokens
    output_per_mtok: Decimal  # USD per 1M output tokens


class InferenceConfig(BaseModel):
    """Runtime-mutable inference configuration.

    Persisted at INFERENCE_CONFIG_PATH as JSON (pydantic v2 model_dump_json /
    model_validate_json). The file is gitignored via .secrets/.

    Note: spec originally mentioned TOML; JSON was chosen for robust Decimal
    round-trip support via pydantic v2 without an extra dependency.

    Strict: an unknown key (a typo such as ``spend_cap``) is an error rather than
    a silently ignored setting (docs/DECISIONS.md#adr-local-first-inference).
    """

    model_config = ConfigDict(extra="forbid")

    orchestrator: RoleConfig
    worker: RoleConfig
    limits: dict[ProviderType, ProviderLimits] = Field(default_factory=dict)
    spend_cap_usd: Decimal | None = Field(default=None, ge=0)
    pricing_overrides: dict[str, ModelPrice] = Field(default_factory=dict)
    # Portfolio data goes to a cloud orchestrator only with this explicit
    # opt-in; off by default (docs/DECISIONS.md#adr-advisory-pipeline).
    allow_cloud_advisory: bool = False


# Path constant: .secrets/ is gitignored; the file is created on first save.
INFERENCE_CONFIG_PATH: Path = Path(".secrets/inference.json")


# The inference config holds raw cloud API keys in cleartext, so it must never
# be readable by other local accounts (CWE-276). Owner-only mode bits for the
# file and its containing directory; POSIX-only (see _restrict_mode).
SECRET_FILE_MODE: int = 0o600


SECRET_DIR_MODE: int = 0o700


def _restrict_mode(fd: int, mode: int, target: Path) -> None:
    """Best-effort chmod of the already-open descriptor *fd* to *mode*.

    Always operates on a descriptor, never on a path: the mode then lands on
    the exact object this process opened and cannot be redirected through a
    symlink (CWE-59), nor swapped out between a check and the chmod. *target*
    is used for logging only.

    No-op on non-POSIX platforms: Windows has no POSIX mode bits (os.chmod
    there only toggles the read-only flag, and os.fchmod does not exist), so
    applying them is meaningless. The project targets POSIX — CI runs on
    ubuntu-latest, the documented hardware target is Apple Silicon, and the
    helper scripts are shell scripts — but this stays defensive so a save
    never raises on another platform.

    A chmod failure (filesystem without permission support, file owned by
    another user) is logged and swallowed rather than turned into a failed
    save: the secret file itself is already *created* with restrictive bits,
    so this call is a repair for pre-existing paths, not the primary control.
    """
    if os.name != "posix":
        return
    try:
        os.fchmod(fd, mode)
    except OSError as exc:
        logger.warning(
            "secret_permissions_not_restricted",
            target=str(target),
            mode=oct(mode),
            error=str(exc),
        )


def _restrict_dir_mode(directory: Path, mode: int) -> None:
    """Best-effort chmod of *directory* to *mode*, refusing to follow symlinks.

    ``Path.mkdir(parents=True, exist_ok=True)`` succeeds when the directory
    entry is a *symlink* to an existing directory, so a plain path-based
    ``os.chmod`` here would let anyone able to create that entry redirect the
    mode change onto an unrelated directory the operator owns — stripping
    group/other access and setgid/sticky bits from it (CWE-59). Opening with
    ``O_DIRECTORY | O_NOFOLLOW`` instead fails cleanly (ELOOP/ENOTDIR) on a
    symlinked directory, and fchmod applies to the object actually opened, so
    there is no check-then-act window either. A failure is logged and skipped;
    the secret file's own 0600 creation mode is unaffected.
    """
    if os.name != "posix":
        return
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        logger.warning(
            "secret_permissions_not_restricted",
            target=str(directory),
            mode=oct(mode),
            error=str(exc),
        )
        return
    try:
        _restrict_mode(fd, mode, directory)
    finally:
        os.close(fd)


def default_inference_config(app_settings: AppSettings) -> InferenceConfig:
    """Return a local-only default InferenceConfig from OllamaSettings.

    Both roles are OLLAMA backed, using the alias model names and base_url
    from app_settings.ollama. No API keys, no limits, no spend cap.
    The file at INFERENCE_CONFIG_PATH need not exist for this function.
    """
    role = RoleConfig(
        provider=ProviderType.OLLAMA,
        model="",  # placeholder; overwritten below per role
        base_url=app_settings.ollama.base_url,
        api_key=None,
    )
    orchestrator = role.model_copy(update={"model": app_settings.ollama.orchestrator_model_alias})
    worker = role.model_copy(update={"model": app_settings.ollama.worker_model_alias})
    return InferenceConfig(
        orchestrator=orchestrator,
        worker=worker,
        limits={},
        spend_cap_usd=None,
        pricing_overrides={},
    )


def load_inference_config(
    app_settings: AppSettings,
    path: Path | None = None,
) -> InferenceConfig:
    """Load InferenceConfig from *path* (default: the anchored settings path).

    Falls back to local defaults when the file does not exist; raises ValueError
    when it exists but is invalid. The message names each rejected key path and
    error type, never a value: the file holds API keys, and one stored under a
    misspelled key would otherwise be echoed (the chain is cut with ``from None``
    for the same reason). The file is never rewritten here.
    """
    target = (
        path
        if path is not None
        else app_settings.resolve_path(
            app_settings.inference_config_path,
        )
    )
    if not target.exists():
        return default_inference_config(app_settings)
    raw = target.read_text(encoding="utf-8")
    try:
        return InferenceConfig.model_validate_json(raw)
    except ValidationError as exc:
        problems = _config_error_summary(exc)
    raise InferenceConfigFileError(target, problems) from None


def _config_error_summary(exc: ValidationError) -> str:
    """``"<dotted key path> <error type>"`` per error, joined by ``"; "``; never input values."""
    parts = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = ".".join(str(part) for part in err["loc"]) or "(root)"
        parts.append(f"{loc} {err['type']}")
    return "; ".join(parts)


def save_inference_config(
    cfg: InferenceConfig,
    path: Path | None = None,
    *,
    settings: AppSettings | None = None,
) -> None:
    """Persist *cfg* as pretty-printed JSON at *path*.

    *path* defaults to ``settings.inference_config_path`` resolved against the
    repo root (``settings.resolve_path``) when *settings* is given, else to
    ``PROJECT_ROOT / INFERENCE_CONFIG_PATH``; never to the working directory.

    Creates intermediate directories if they do not exist.

    Writes atomically (temp file in the same directory + os.replace) so an
    interrupted write (crash / full disk) leaves the existing valid config
    untouched rather than a truncated file that breaks every subsequent load
    (F-25).

    The file stores API keys in cleartext, so on POSIX it is owner-only
    (SECRET_FILE_MODE) and its directory is owner-only (SECRET_DIR_MODE)
    (CWE-276). The mode is applied at *creation* of the temp file — the
    cleartext key is never on disk world-readable, not even briefly — and
    os.replace carries the temp file's mode onto the destination, so a config
    file previously written as 0644 is repaired on the next save.
    """
    if path is None:
        path = (
            settings.resolve_path(settings.inference_config_path)
            if settings is not None
            else PROJECT_ROOT / INFERENCE_CONFIG_PATH
        )
    path.parent.mkdir(parents=True, exist_ok=True, mode=SECRET_DIR_MODE)
    # mkdir(mode=...) does nothing for a directory that already exists, so an
    # existing 0755 .secrets/ needs an explicit chmod. Skipped (not redirected)
    # if that directory is a symlink — see _restrict_dir_mode.
    _restrict_dir_mode(path.parent, SECRET_DIR_MODE)

    tmp = path.with_name(f"{path.name}.tmp")
    try:
        # os.open with an explicit mode (not write_text, which creates at
        # 0666 & ~umask) so the temp file never exists with permissive bits.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, SECRET_FILE_MODE)
        try:
            # O_CREAT applies the mode only when it creates the file; a stale
            # temp file left behind by an interrupted save would keep its old
            # mode, so re-apply it on the open descriptor.
            _restrict_mode(fd, SECRET_FILE_MODE, tmp)
            handle = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            handle.write(cfg.model_dump_json(indent=2))
        os.replace(tmp, path)  # atomic on the same filesystem; keeps tmp's mode
    finally:
        # Clean up the temp file if the replace never happened.
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def masked_config(cfg: InferenceConfig) -> dict[str, Any]:
    """Return a JSON-serialisable dict with API keys replaced by mask objects.

    Each role's ``api_key`` is replaced by::

        {"set": bool(key), "last4": key[-4:] if key else None}

    The raw key NEVER appears in the output. All other fields (provider,
    model, base_url, limits, spend_cap_usd, pricing_overrides) are included
    as-is, with Decimal values serialised as strings for JSON safety.
    """
    # Serialise via pydantic (handles Decimal → str, enums → values, etc.)
    raw: dict[str, Any] = cfg.model_dump(mode="json")

    def _mask_role(role_dict: dict[str, Any]) -> dict[str, Any]:
        key: str | None = role_dict.get("api_key")
        role_dict["api_key"] = {
            "set": bool(key),
            "last4": key[-4:] if key else None,
        }
        return role_dict

    raw["orchestrator"] = _mask_role(raw["orchestrator"])
    raw["worker"] = _mask_role(raw["worker"])
    return raw
