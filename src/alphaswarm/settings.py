"""Process settings for AlphaSwarm, loaded from the environment and .env.

pydantic-settings with prefix ``ALPHASWARM_`` and ``__`` for nesting. Inference
provider configuration (which can hold API keys) lives in
``alphaswarm.inference.config``, not here.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Literal

import structlog
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = structlog.get_logger(component="settings")

#: Repository root. Relative runtime paths (.env, reports/, advisory/, the holdings
#: CSV, .secrets/inference.json) resolve against it, never against the working
#: directory (docs/DECISIONS.md#adr-web-lifespan).
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Nested settings models
# ---------------------------------------------------------------------------


class OllamaSettings(BaseModel):
    """Ollama inference server configuration."""

    # Model decision 2026-06-11: MLX-format variants (OLLAMA_USE_MLX=1,
    # >=32GB) — 2.8x worker prefill, 30x orchestrator prefill vs GGUF on
    # M1 Max. See modelfiles/ for benchmarks and requirements.
    orchestrator_model: str = "qwen3.6:27b-nvfp4"
    worker_model: str = "qwen3.6:35b-a3b-nvfp4"
    base_url: str = "http://localhost:11434"
    # Per-role HTTP timeouts (docs/DECISIONS.md#adr-inference-timeouts). Worker
    # calls take seconds on MLX, so a stalled one is cut at 120 s; orchestrator
    # calls, model loads and warm-ups keep 600 s. An unreachable host fails at
    # the 5 s connect timeout.
    connect_timeout_s: float = Field(default=5.0, ge=0.5, le=60.0)
    worker_read_timeout_s: float = Field(default=120.0, ge=10.0, le=3600.0)
    orchestrator_read_timeout_s: float = Field(default=600.0, ge=30.0, le=3600.0)
    orchestrator_model_alias: str = "alphaswarm-orchestrator"
    worker_model_alias: str = "alphaswarm-worker"
    # Mirrors PARAMETER num_ctx in modelfiles/Modelfile.worker (pinned by
    # tests/invariants/test_modelfile_mirrors.py). Used only to flag prompts near
    # the context limit (r{n}_ctx_warnings); never sent per request
    # (docs/DECISIONS.md#adr-model-aliases).
    worker_num_ctx: int = Field(default=4096, ge=512, le=262144)

    @model_validator(mode="before")
    @classmethod
    def _map_legacy_timeout(cls, data: Any) -> Any:
        """Map the retired request_timeout_seconds onto the orchestrator read timeout."""
        if not isinstance(data, dict) or "request_timeout_seconds" not in data:
            return data
        mapped = dict(data)
        legacy = mapped.pop("request_timeout_seconds")
        mapped.setdefault("orchestrator_read_timeout_s", legacy)
        warnings.warn(
            "ALPHASWARM_OLLAMA__REQUEST_TIMEOUT_SECONDS is retired; it now sets "
            "ALPHASWARM_OLLAMA__ORCHESTRATOR_READ_TIMEOUT_S. Rename it in .env.",
            FutureWarning,
            stacklevel=2,
        )
        return mapped

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_keys(cls, data: Any) -> Any:
        """Ignore num_parallel / max_loaded_models from old .env files.

        They were never read; server parallelism and the loaded-model count are
        Ollama server variables (docs/DECISIONS.md#adr-model-aliases).
        """
        if not isinstance(data, dict):
            return data
        retired = sorted(k for k in ("num_parallel", "max_loaded_models") if k in data)
        if not retired:
            return data
        log.warning(
            "ollama_retired_settings_ignored",
            keys=retired,
            hint="set OLLAMA_NUM_PARALLEL / OLLAMA_MAX_LOADED_MODELS on the Ollama server",
        )
        return {k: v for k, v in data.items() if k not in retired}


class Neo4jSettings(BaseModel):
    """Neo4j graph database connection configuration."""

    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    # No literal default (CWE-798): a hardcoded password here is not a
    # placeholder — it is the credential every default deployment actually
    # authenticates with, published in this repository. Supply it via
    # ALPHASWARM_NEO4J__PASSWORD (environment or .env).
    #
    # The empty default keeps AppSettings constructible for the many code
    # paths that never open a Neo4j connection (CLI banner, web unit tests,
    # inference-only flows). Every path that DOES open a driver must read the
    # credential through require_password(), which fails loudly when unset.
    password: str = ""
    database: str = "neo4j"
    # Server-side transaction timeout applied to every GraphStateManager
    # read/write, and the driver's wait for a pooled connection
    # (docs/DECISIONS.md#p4-d-07).
    query_timeout_s: float = Field(default=30.0, ge=1.0, le=600.0)
    connection_acquisition_timeout: float = Field(default=10.0, ge=1.0, le=120.0)

    def require_password(self) -> str:
        """Return the configured password, raising if none was supplied.

        Called at driver-construction time so a missing credential surfaces as
        an actionable startup error rather than an opaque Neo4j auth failure,
        and so no deployment silently falls back to a published default.
        """
        if not self.password:
            raise ValueError(
                "Neo4j password is not configured. Set ALPHASWARM_NEO4J__PASSWORD "
                "(environment variable or .env) to the password your Neo4j "
                "instance was created with — there is no default."
            )
        return self.password


class GovernorSettings(BaseModel):
    """Resource governor thresholds for memory-aware throttling."""

    baseline_parallel: int = Field(default=8, ge=1, le=32)
    max_parallel: int = Field(default=16, ge=1, le=32)
    memory_throttle_percent: float = Field(default=80.0, ge=50.0, le=95.0)
    memory_pause_percent: float = Field(default=90.0, ge=60.0, le=99.0)
    check_interval_seconds: float = Field(default=2.0, ge=0.5, le=10.0)

    # Phase 3: Dynamic governor fields (D-01, D-02, D-04, D-05, D-07, D-14)
    scale_up_threshold_percent: float = Field(default=60.0, ge=30.0, le=80.0)
    scale_up_consecutive_checks: int = Field(default=3, ge=1, le=10)
    crisis_timeout_seconds: float = Field(default=300.0, ge=30.0, le=600.0)
    slot_adjustment_step: int = Field(default=2, ge=1, le=4)
    batch_failure_threshold_percent: float = Field(default=20.0, ge=5.0, le=50.0)
    # Rolling-window failure accounting (docs/DECISIONS.md#p3-d-04): over the
    # last failure_window_size inference outcomes, a failure share of at least
    # batch_failure_threshold_percent shrinks one slot_adjustment_step;
    # failure_regrow_successes consecutive successes grow one step back.
    failure_window_size: int = Field(default=20, ge=4, le=200)
    failure_regrow_successes: int = Field(default=10, ge=1, le=100)
    jitter_min_seconds: float = Field(default=0.5, ge=0.0, le=2.0)
    # Lower bound 0.0 lets deterministic harnesses (tests/engine) turn jitter off;
    # the production default stays 1.5 s (docs/DECISIONS.md#p3-d-14).
    jitter_max_seconds: float = Field(default=1.5, ge=0.0, le=5.0)
    # Abort a round before persisting it when more than this share of agents
    # failed; 100 disables the abort (docs/DECISIONS.md#adr-taskgroup-dispatch).
    round_abort_failure_percent: float = Field(default=50.0, ge=1.0, le=100.0)

    @model_validator(mode="after")
    def _check_threshold_ordering(self) -> GovernorSettings:
        """Enforce the ordering the governor's throttle ladder depends on (F-31).

        Each Field bound is validated independently, so env vars could set e.g.
        PAUSE < THROTTLE or SCALE_UP > THROTTLE — individually valid but
        semantically inverted, causing the governor to pause before throttling
        or scale up while already memory-pressured. Fail fast at startup instead.
        """
        if not (self.scale_up_threshold_percent < self.memory_throttle_percent < self.memory_pause_percent):
            raise ValueError(
                "GovernorSettings ordering invariant violated: require "
                "scale_up_threshold_percent < memory_throttle_percent < "
                "memory_pause_percent, got "
                f"{self.scale_up_threshold_percent} / "
                f"{self.memory_throttle_percent} / {self.memory_pause_percent}"
            )
        if self.jitter_min_seconds > self.jitter_max_seconds:
            raise ValueError(
                "GovernorSettings: jitter_min_seconds must be <= jitter_max_seconds, "
                f"got {self.jitter_min_seconds} > {self.jitter_max_seconds}"
            )
        if self.baseline_parallel > self.max_parallel:
            raise ValueError(
                "GovernorSettings: baseline_parallel must be <= max_parallel, "
                f"got {self.baseline_parallel} > {self.max_parallel}"
            )
        return self


class SimulationSettings(BaseModel):
    """Engine experiment knobs (docs/DECISIONS.md#adr-diverse-peer-context).

    Holds the peer-selection parameters and the experiment knobs
    (docs/DECISIONS.md#adr-run-manifest). Every cycle records the effective values in its metrics, so
    runs stay comparable when a knob changes. Env: ALPHASWARM_SIMULATION__<FIELD>.
    """

    # Peers shown to each reader per round; also the formatter's line limit.
    peer_limit: int = Field(default=10, ge=1, le=20)
    # Distinct brackets guaranteed per reader (best effort when fewer remain).
    min_brackets: int = Field(default=4, ge=0, le=10)
    # Most peers a single bracket may fill in one reader's feed (hard cap).
    bracket_cap: int = Field(default=3, ge=1, le=10)
    # Weight added to authors the reader cited last round. 0.3 is the documented
    # default; only an ablation may change it.
    personal_boost: float = Field(default=0.3, ge=0.0, le=1.0)
    # Character budget of one reader's rendered peer block.
    peer_budget_chars: int = Field(default=4000, ge=500, le=16000)
    # --- Experiment knobs (docs/DECISIONS.md#adr-run-manifest) ----------------
    # "stratified": seeded stratified sampling; "random": a uniform sample of the
    # eligible peers; "none": nobody sees peers (an ablation arm).
    peer_strategy: Literal["stratified", "random", "none"] = "stratified"
    # Show each agent its own previous decision in Rounds 2..N.
    own_prior_memory: bool = True
    # Rounds 1..N that receive the market block (0 = none).
    market_context_rounds: int = Field(default=3, ge=0, le=3)
    # Authority cues on peer lines: False drops "|bracket" or "(conf: x.xx)".
    show_bracket_labels: bool = True
    show_confidence: bool = True
    # One sampling temperature for every agent; None keeps per-bracket temperatures.
    uniform_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    # Seeded share of each bracket that never sees peers (d.control). Product
    # default off; experiment runs set 0.2 (docs/DECISIONS.md#adr-diverse-peer-context).
    control_fraction: float = Field(default=0.0, ge=0.0, le=0.5)
    # Show shocks to a seeded half of each bracket only (causal shock effect).
    shock_treatment_split: bool = False
    # Seed for peer draws, the holdout and per-call model seeds. None derives one
    # from the cycle id; the run manifest records the effective value.
    sim_seed: int | None = Field(default=None, ge=1, le=2_147_483_647)
    # Label that groups cycles in scripts/compare_cycles.py --group-by.
    experiment_tag: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    # Dispatch Round 1 a second time with fresh seeds to measure the noise floor.
    retest_round1: bool = False
    # Seeded per-agent traits in every persona (docs/DECISIONS.md#adr-persona-traits).
    persona_traits: bool = True


# ---------------------------------------------------------------------------
# Root application settings
# ---------------------------------------------------------------------------


# The two ways the operator actually reaches the UI: the Vite dev server (5173)
# and the uvicorn app that also serves the built SPA (8000), on both loopback
# spellings. One list serves the WebSocket handshake and the HTTP CSRF guard
# (docs/DECISIONS.md#adr-security-2026-08).
DEFAULT_ALLOWED_ORIGINS: Final[tuple[str, ...]] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
)


# Host header values the server answers (DNS-rebinding defence). Hosts only, no
# port: Starlette's TrustedHostMiddleware compares the part before the first ":".
DEFAULT_TRUSTED_HOSTS: Final[tuple[str, ...]] = ("localhost", "127.0.0.1", "[::1]")


# The per-channel origin variables that ALPHASWARM_ALLOWED_ORIGINS replaced.
LEGACY_ORIGIN_ENV_VARS: Final[tuple[str, ...]] = (
    "ALPHASWARM_HTTP_ALLOWED_ORIGINS",
    "ALPHASWARM_WS_ALLOWED_ORIGINS",
)


def legacy_origin_settings(environ: Mapping[str, str], env_file: Path | None) -> list[str]:
    """Names of the removed per-channel origin variables set in *environ* or *env_file*.

    They are no longer read; create_app logs a warning so a customised value is not
    lost silently. The .env file is scanned for keys only, never values.
    """
    found = {name for name in LEGACY_ORIGIN_ENV_VARS if name in environ}
    if env_file is not None and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip().removeprefix("export ").strip()
            if key in LEGACY_ORIGIN_ENV_VARS:
                found.add(key)
    return sorted(found)


class AppSettings(BaseSettings):
    """Root configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_prefix="ALPHASWARM_",
        env_nested_delimiter="__",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AlphaSwarm"
    debug: bool = False
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        """Accept any case (ALPHASWARM_LOG_LEVEL=info); the pattern then checks the name."""
        return value.upper() if isinstance(value, str) else value

    # Consensus cascade depth. 3 = R1 prior + two peer rounds (legacy default,
    # full UI compat). 2 = R1 prior + one peer round — the A/B candidate that
    # saves ~35-45 min/cycle on M1 Max; most opinion flips happen in R2.
    # Flip via ALPHASWARM_NUM_ROUNDS=2. SimulationResult round3 fields are
    # empty when only 2 rounds run.
    num_rounds: int = Field(default=3, ge=2, le=3)

    ollama: OllamaSettings = OllamaSettings()
    neo4j: Neo4jSettings = Neo4jSettings()
    governor: GovernorSettings = GovernorSettings()
    simulation: SimulationSettings = SimulationSettings()

    # Phase 39 HOLD-01/HOLD-03, D-05: CSV path for HoldingsLoader, eager-loaded at lifespan startup.
    # env_prefix="ALPHASWARM_" maps this flat field to env var ALPHASWARM_HOLDINGS_CSV_PATH.
    # pydantic-settings v2 coerces string env values to pathlib.Path automatically.
    holdings_csv_path: Path = Path("Schwab/holdings.csv")

    # Curated ticker -> sector map for the advisory (owner data, gitignored). Relative
    # paths resolve against PROJECT_ROOT; when the file is missing the fictional
    # examples/sector_map.example.json is used (docs/DECISIONS.md#adr-holdings-isolation).
    # Env ALPHASWARM_SECTOR_MAP_PATH.
    sector_map_path: Path = Path("data/sector_map.local.json")

    # Cached SEC company ticker map used to validate seed-entity tickers (public data,
    # gitignored; fetch with scripts/fetch_ticker_map.py). Relative paths resolve
    # against PROJECT_ROOT. A missing file is fine: the resolver falls back to its
    # no-map rule. Env ALPHASWARM_TICKER_MAP_PATH (docs/DECISIONS.md#adr-ticker-resolution).
    ticker_map_path: Path = Path("data/sec_tickers.json")

    # Runtime inference config (provider choice, cloud API keys), written by the
    # Settings UI. Injectable so tests point it at a temp file and never read the
    # operator's real one (docs/DECISIONS.md#adr-tests-scoped-cleanup). Env var:
    # ALPHASWARM_INFERENCE_CONFIG_PATH. Relative paths resolve against PROJECT_ROOT
    # (resolve_path). Same value as inference.config.INFERENCE_CONFIG_PATH, written
    # out because settings.py sits below inference/ in the import graph.
    inference_config_path: Path = Path(".secrets/inference.json")

    # Output directories for report markdown and advisory JSON. Relative values
    # resolve against PROJECT_ROOT (see resolve_path).
    reports_dir: Path = Path("reports")
    advisory_dir: Path = Path("advisory")
    # Advisory JSON holds cost-basis exposure, so only the newest N files are kept
    # (docs/DECISIONS.md#adr-holdings-isolation). Env ALPHASWARM_ADVISORY_KEEP_LAST.
    advisory_keep_last: int = Field(default=20, ge=1)

    def resolve_path(self, p: Path) -> Path:
        """Return *p* as an absolute path; relative paths are anchored at PROJECT_ROOT."""
        expanded = p.expanduser()
        return expanded if expanded.is_absolute() else PROJECT_ROOT / expanded

    # One origin allow-list for the unauthenticated /ws/state handshake and for
    # state-changing HTTP requests (CSRF, CWE-352); see web/origin_guard.py and
    # docs/DECISIONS.md#adr-security-2026-08. JSON list in ALPHASWARM_ALLOWED_ORIGINS,
    # e.g. ["http://localhost:5173","http://192.168.1.20:8000"]. Entries compare as
    # scheme://host[:port] with case and default ports folded.
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS

    # Host header values the server answers (TrustedHostMiddleware, DNS-rebinding
    # defence, installed in web/app.py). JSON list in ALPHASWARM_TRUSTED_HOSTS;
    # hosts only, no port. Entries are lower-cased, and a malformed one fails
    # startup (web/origin_guard.normalized_trusted_hosts).
    trusted_hosts: tuple[str, ...] = DEFAULT_TRUSTED_HOSTS
