# Phase 1: Project Foundation - Research

**Researched:** 2026-03-24
**Domain:** Python project scaffolding, Pydantic configuration, structlog structured logging, uv packaging
**Confidence:** HIGH

## Summary

Phase 1 establishes the runnable project scaffold for AlphaSwarm: a `uv`-managed Python package with Pydantic-based configuration, structured logging via structlog with per-agent correlation IDs, and all 100 agent persona definitions across 10 bracket archetypes. No inference, graph queries, or TUI rendering happens in this phase -- only interfaces, contracts, and type definitions.

The primary technical challenges are: (1) designing a Pydantic settings hierarchy that cleanly represents bracket archetypes, per-agent personas, and Ollama/Neo4j connection config while remaining overridable via environment variables; (2) configuring structlog for JSON output with asyncio-safe context variable binding for per-agent correlation; (3) structuring the Python package so that `uv run python -m alphaswarm` produces a clean startup banner and validates all configuration on boot.

**Primary recommendation:** Use `uv init --package alphaswarm` to scaffold a `src/alphaswarm/` layout, define a comprehensive `AppSettings(BaseSettings)` with nested models for each config domain, configure structlog with `merge_contextvars` as the first processor in the chain for correlation ID propagation, and define all 100 agent personas as structured config data loaded at startup.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
1. **Adaptive Resource Management:** Implementation must use a `ResourceGovernor` class. It should wrap an `asyncio.Semaphore` and use `psutil` to dynamically shrink/grow the concurrent request slots based on a 90% memory pressure ceiling. (Note: Full ResourceGovernor implementation is Phase 3 -- Phase 1 establishes the type stubs and interface contracts.)
2. **Decoupled UI Rendering:** In `ui.py`, use a snapshot-based rendering loop (200ms ticks) that reads from a shared state dictionary. Do not allow individual agent updates to trigger UI refreshes; the TUI must be the "observer." (Note: Full TUI implementation is Phase 9 -- Phase 1 establishes the StateStore interface and shared state contract.)
3. **Modular Entry Point:** `main.py` must initialize the ResourceGovernor, the Neo4j driver, and the Textual app as global singletons (or via a clean AppState container) to prevent circular imports as we scale to 100 agents.
4. Use `uv` for package management with `pyproject.toml`
5. Models: `qwen3:32b` (orchestrator), `qwen3.5:4b` (workers) -- corrected from original spec
6. All 10 brackets: Quants (10), Degens (20), Sovereigns (10), Macro (10), Suits (10), Insiders (10), Agents (15), Doom-Posters (5), Policy Wonks (5), Whales (5)
7. AppState container pattern preferred over scattered global singletons

### Scope Constraints
- Focus strictly on environment setup, dependency management (uv/pyproject.toml), and the type/config foundation
- Do NOT start Miro logic
- Do NOT implement actual inference, graph queries, or TUI rendering -- only interfaces and contracts

### Claude's Discretion
- Project directory structure and module organization
- Pydantic model field names and validation rules beyond what's specified in requirements
- structlog configuration details (processors, output format)
- Which bracket attributes to include in persona definitions beyond the basics (name, count, risk_profile, temperature, system_prompt_template, influence_weight_base)

### Deferred Ideas (OUT OF SCOPE)
- ResourceGovernor full implementation (Phase 3)
- Neo4j connection and schema (Phase 4)
- TUI full rendering (Phase 9)
- Miro batcher (Phase 8)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CONF-01 | Pydantic-based settings model for all configurable parameters (model tags, parallelism limits, memory thresholds, Neo4j connection, bracket definitions) | Pydantic-settings v2 BaseSettings with nested models and env_nested_delimiter, validated via Field constraints and custom validators |
| CONF-02 | Agent persona definitions for all 10 brackets stored as structured config (name, count, risk_profile, temperature, system_prompt template, influence_weight_base) | Frozen Pydantic BaseModel for BracketConfig and AgentPersona, loaded from defaults in config module with total agent count validation |
| INFRA-11 | structlog-based logging with per-agent correlation IDs via context binding | structlog 25.5.0 with contextvars.merge_contextvars processor, JSONRenderer, and bind_contextvars for agent_id/bracket/cycle_id correlation |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Python 3.11+ required.** Strong typing throughout.
- **Concurrency is mandatory:** Use `asyncio` for all LLM inference and API calls.
- **Ollama Constraints:** Assume `OLLAMA_NUM_PARALLEL=16` and `OLLAMA_MAX_LOADED_MODELS=2`.
- **Memory Pressure:** Implement basic telemetry to monitor local RAM. If pressure is high, pause the task queue.
- **Miro API:** Strict 2-second buffer/batching. (Phase 1: NOT implemented, only interface contract.)
- **Ruflo v3.5:** Research confirmed this is NOT a Python library. Replaced with custom asyncio orchestration per STACK.md findings.
- **Model corrections:** `llama4:70b` does not exist (use corrected models per CONTEXT.md); `qwen3.5:7b` does not exist (use `qwen3.5:4b`).

## Standard Stack

### Core (Phase 1 Dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | >=2.12.5 | Data models, type definitions | Runtime validation, JSON schema generation, frozen models for agent personas. Industry standard. |
| pydantic-settings | >=2.13.1 | Environment/config loading | BaseSettings with env var mapping, .env support, nested model delimiter. Official Pydantic companion. |
| structlog | >=25.5.0 | Structured logging | JSON output, context variable binding for per-agent correlation, async log methods. Best Python structured logger. |
| psutil | >=7.2.2 | System monitoring stub | Phase 1 only needs the import for ResourceGovernor interface contract. Full use in Phase 3. |

### Supporting (Dev Dependencies for Phase 1)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | >=8.x | Test runner | Validate config loading, persona definitions, log output |
| pytest-asyncio | >=0.24.x | Async test support | Test async startup sequence and AppState initialization |
| ruff | latest | Linter + formatter | All code formatting and linting |
| mypy | latest | Type checker | Enforce strong typing constraint |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pydantic-settings | python-dotenv + dataclasses | Loses validation, env nesting, and type coercion. Not worth it. |
| structlog | loguru | No native async log methods, no contextvars binding, less structured JSON output |
| structlog | stdlib logging | No context binding, no JSON renderer, verbose configuration |

**Installation:**
```bash
# Install uv first (not currently on this machine)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Initialize project as a package
uv init --package alphaswarm

# Core dependencies
uv add pydantic pydantic-settings structlog psutil

# Dev dependencies
uv add --dev pytest pytest-asyncio ruff mypy
```

**Version verification:** All versions verified via PyPI as of 2026-03-24.
- pydantic: 2.12.5 (latest stable)
- pydantic-settings: 2.13.1 (released 2026-02-19)
- structlog: 25.5.0 (latest stable)
- psutil: 7.2.2 (released 2026-01-28)

## Architecture Patterns

### Recommended Project Structure

```
alphaswarm/
├── .python-version          # "3.11" (uv manages this)
├── pyproject.toml           # PEP 621, all deps, scripts, tool config
├── uv.lock                  # Auto-generated lockfile
├── .env.example             # Documented env vars (committed)
├── .env                     # Local overrides (gitignored)
├── src/
│   └── alphaswarm/
│       ├── __init__.py      # Package version, minimal
│       ├── __main__.py      # Entry point: `python -m alphaswarm`
│       ├── config.py        # Pydantic settings models, bracket definitions
│       ├── types.py         # Core type definitions (BracketType, AgentPersona, etc.)
│       ├── logging.py       # structlog configuration
│       ├── state.py         # StateStore interface contract (stub)
│       ├── governor.py      # ResourceGovernor interface contract (stub)
│       └── app.py           # AppState container, initialization logic
└── tests/
    ├── conftest.py
    ├── test_config.py
    └── test_types.py
```

### Pattern 1: AppState Container

**What:** A single container class that holds all shared state (config, logger, future Neo4j driver, future ResourceGovernor) to prevent circular imports and scattered globals.

**When to use:** At application startup in `__main__.py`. Passed to all subsystems as a dependency.

**Example:**
```python
# Source: CONTEXT.md locked decision + architecture patterns
from dataclasses import dataclass, field
from alphaswarm.config import AppSettings
from alphaswarm.governor import ResourceGovernor
from alphaswarm.state import StateStore
import structlog

@dataclass
class AppState:
    """Central application state container. Initialized once at startup."""
    settings: AppSettings
    logger: structlog.stdlib.BoundLogger
    governor: ResourceGovernor  # Stub in Phase 1
    state_store: StateStore     # Stub in Phase 1
    # neo4j_driver: AsyncDriver  # Added in Phase 4
    # ollama_client: AsyncClient  # Added in Phase 2
```

### Pattern 2: Pydantic Settings with Nested Models

**What:** A hierarchical settings model where each subsystem has its own nested config model, all loaded from env vars with `__` delimiter.

**When to use:** Loading and validating all configuration at startup before any subsystem initializes.

**Example:**
```python
# Source: pydantic-settings v2 official docs
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class OllamaSettings(BaseModel):
    """Ollama-specific configuration."""
    orchestrator_model: str = "qwen3:32b"
    worker_model: str = "qwen3.5:4b"
    num_parallel: int = Field(default=16, ge=1, le=32)
    max_loaded_models: int = Field(default=2, ge=1, le=4)
    base_url: str = "http://localhost:11434"

class Neo4jSettings(BaseModel):
    """Neo4j connection configuration."""
    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "alphaswarm"
    database: str = "neo4j"

class GovernorSettings(BaseModel):
    """ResourceGovernor configuration."""
    baseline_parallel: int = Field(default=8, ge=1, le=32)
    max_parallel: int = Field(default=16, ge=1, le=32)
    memory_throttle_percent: float = Field(default=80.0, ge=50.0, le=95.0)
    memory_pause_percent: float = Field(default=90.0, ge=60.0, le=99.0)
    check_interval_seconds: float = Field(default=2.0, ge=0.5, le=10.0)

class AppSettings(BaseSettings):
    """Root settings model. Loads from env vars and .env file."""
    model_config = SettingsConfigDict(
        env_prefix="ALPHASWARM_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    app_name: str = "AlphaSwarm"
    debug: bool = False
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    ollama: OllamaSettings = OllamaSettings()
    neo4j: Neo4jSettings = Neo4jSettings()
    governor: GovernorSettings = GovernorSettings()
```

**Env var mapping with `ALPHASWARM_` prefix and `__` delimiter:**
```bash
ALPHASWARM_DEBUG=true
ALPHASWARM_LOG_LEVEL=DEBUG
ALPHASWARM_OLLAMA__ORCHESTRATOR_MODEL=qwen3:32b
ALPHASWARM_OLLAMA__NUM_PARALLEL=8
ALPHASWARM_NEO4J__URI=bolt://localhost:7687
ALPHASWARM_GOVERNOR__BASELINE_PARALLEL=8
```

### Pattern 3: Frozen Agent Persona Model

**What:** Immutable Pydantic models for agent personas. Defined once at config load, never mutated during simulation.

**When to use:** Defining the 100 agent identities at startup. Runtime state (decisions, sentiment) lives elsewhere.

**Example:**
```python
from enum import Enum
from pydantic import BaseModel, Field

class BracketType(str, Enum):
    QUANTS = "quants"
    DEGENS = "degens"
    SOVEREIGNS = "sovereigns"
    MACRO = "macro"
    SUITS = "suits"
    INSIDERS = "insiders"
    AGENTS = "agents"
    DOOM_POSTERS = "doom_posters"
    POLICY_WONKS = "policy_wonks"
    WHALES = "whales"

class BracketConfig(BaseModel, frozen=True):
    """Immutable bracket archetype definition."""
    bracket_type: BracketType
    display_name: str
    count: int = Field(ge=1, le=100)
    risk_profile: float = Field(ge=0.0, le=1.0)
    temperature: float = Field(ge=0.0, le=2.0)
    system_prompt_template: str
    influence_weight_base: float = Field(ge=0.0, le=1.0)

class AgentPersona(BaseModel, frozen=True):
    """Immutable agent identity. Created once at startup."""
    id: str                           # e.g., "quant_03"
    name: str                         # Human-readable name
    bracket: BracketType
    risk_profile: float
    temperature: float
    system_prompt: str                # Fully rendered from template
    influence_weight_base: float
```

### Pattern 4: structlog JSON Configuration with Context Variables

**What:** Configure structlog once at startup for JSON output with context variable merging. Use `bind_contextvars` in async tasks for per-agent log correlation.

**When to use:** Called once in `logging.py`, imported by `__main__.py` during startup.

**Example:**
```python
# Source: structlog 25.5.0 official docs
import logging
import structlog

def configure_logging(log_level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog for the application. Call once at startup."""

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,  # MUST be first
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    if json_output:
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        # Dev-friendly colored output
        shared_processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

def get_logger(**initial_bindings) -> structlog.stdlib.BoundLogger:
    """Get a logger with optional initial context bindings."""
    return structlog.get_logger(**initial_bindings)
```

**Per-agent correlation usage (future phases):**
```python
import structlog

# At the start of each agent inference task:
structlog.contextvars.clear_contextvars()
structlog.contextvars.bind_contextvars(
    agent_id="quant_03",
    bracket="quants",
    cycle_id="abc-123",
    round_num=1,
)
logger = structlog.get_logger()
await logger.ainfo("agent processing started")
# Output: {"event": "agent processing started", "agent_id": "quant_03",
#          "bracket": "quants", "cycle_id": "abc-123", "round_num": 1,
#          "level": "info", "timestamp": "2026-03-24T..."}
```

### Pattern 5: `__main__.py` Entry Point

**What:** The module entry point that validates config, configures logging, and prints a startup banner.

**When to use:** Invoked via `uv run python -m alphaswarm`.

**Example:**
```python
# src/alphaswarm/__main__.py
import asyncio
import sys

from alphaswarm.config import AppSettings, load_bracket_configs, generate_personas
from alphaswarm.logging import configure_logging, get_logger

def main() -> None:
    """Application entry point."""
    try:
        settings = AppSettings()
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    configure_logging(
        log_level=settings.log_level,
        json_output=not settings.debug,
    )
    logger = get_logger(component="main")

    # Load and validate bracket configs + personas
    brackets = load_bracket_configs()
    personas = generate_personas(brackets)

    logger.info(
        "alphaswarm started",
        version="0.1.0",
        agents_total=len(personas),
        brackets_total=len(brackets),
        orchestrator_model=settings.ollama.orchestrator_model,
        worker_model=settings.ollama.worker_model,
    )

    # Print startup banner
    print("=" * 60)
    print("  AlphaSwarm v0.1.0")
    print(f"  Agents: {len(personas)} across {len(brackets)} brackets")
    print(f"  Orchestrator: {settings.ollama.orchestrator_model}")
    print(f"  Workers: {settings.ollama.worker_model}")
    print("=" * 60)

if __name__ == "__main__":
    main()
```

### Anti-Patterns to Avoid

- **Scattered globals:** Do NOT create module-level `settings = AppSettings()` in multiple files. Use the AppState container, initialized once in `__main__.py` and passed down.
- **Mutable persona definitions:** Agent personas MUST be frozen/immutable. Runtime state (decisions, sentiment) goes in StateStore, not on the persona object.
- **Eager Neo4j/Ollama connection:** Phase 1 must NOT attempt to connect to Neo4j or Ollama. Config defines connection parameters; actual connection happens in later phases.
- **Per-agent logger instances:** Do NOT create 100 separate logger objects. Use `structlog.contextvars.bind_contextvars()` to attach agent context per async task, and a single `structlog.get_logger()` call.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Env var loading + validation | Custom os.environ parsing | pydantic-settings BaseSettings | Type coercion, nested model support, .env files, validation errors with clear messages |
| Structured JSON logging | Custom json.dumps wrapper | structlog with JSONRenderer | Context propagation, async safety, processor chain, timestamp formatting |
| Data validation | Manual assert/if checks | Pydantic BaseModel with Field | Schema generation, serialization, frozen models, rich error messages |
| Enum with string values | Plain string constants | `class BracketType(str, Enum)` | Type safety, exhaustive matching, serialization support |

**Key insight:** Every "simple" config parser eventually grows into a validation framework. Start with Pydantic from day one -- the cost is near-zero and the payoff is immediate (env vars, validation, serialization, schema export).

## Common Pitfalls

### Pitfall 1: pydantic-settings env_prefix Case Sensitivity

**What goes wrong:** Environment variables not being picked up because of case mismatch between the prefix and actual env var names.
**Why it happens:** pydantic-settings v2 is case-insensitive by default for env var names, but the `env_prefix` is applied literally. If you set `env_prefix="ALPHASWARM_"`, the env var must start with `ALPHASWARM_` (uppercase).
**How to avoid:** Always document the exact env var names in `.env.example`. Test with explicit env var injection in tests.
**Warning signs:** Settings loading with unexpected defaults when you expected env overrides.

### Pitfall 2: structlog merge_contextvars Processor Position

**What goes wrong:** Context variables (agent_id, cycle_id) not appearing in log output.
**Why it happens:** `merge_contextvars` must be the FIRST processor in the chain. If placed after other processors, the context is not merged before rendering.
**How to avoid:** Always configure `structlog.contextvars.merge_contextvars` as `processors[0]`.
**Warning signs:** Log lines missing expected context fields despite `bind_contextvars()` calls.

### Pitfall 3: Agent Count Validation Drift

**What goes wrong:** Bracket agent counts don't sum to 100, causing downstream simulation failures.
**Why it happens:** Someone modifies a bracket count without updating others. No runtime check enforces the total.
**How to avoid:** Add a `model_validator` on the settings/config that sums all bracket counts and asserts == 100.
**Warning signs:** "Agent 97 not found" errors in simulation phases. Off-by-one in grid rendering.

### Pitfall 4: uv run vs python -m Invocation

**What goes wrong:** `uv run ./src/alphaswarm` runs `__main__.py` as a script, breaking relative imports.
**Why it happens:** uv mirrors Python's behavior of running directories as scripts. Module invocation requires the `-m` flag.
**How to avoid:** Always use `uv run python -m alphaswarm`, never `uv run ./src/alphaswarm`. Document this in pyproject.toml scripts section.
**Warning signs:** `ImportError: attempted relative import with no known parent package`.

### Pitfall 5: Frozen Model with Mutable Default

**What goes wrong:** Two agents sharing the same mutable default list/dict in their persona definition.
**Why it happens:** Python's mutable default argument trap, combined with Pydantic's `frozen=True` only preventing attribute assignment (not deep immutability).
**How to avoid:** Use `Field(default_factory=list)` for any list/dict fields. Keep persona models simple (all scalars and strings).
**Warning signs:** One agent's data mysteriously changing when another agent is modified.

## Code Examples

Verified patterns from official sources:

### Complete pyproject.toml Configuration

```toml
# Source: uv docs + PEP 621
[project]
name = "alphaswarm"
version = "0.1.0"
description = "Multi-agent financial simulation engine"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.12.5",
    "pydantic-settings>=2.13.1",
    "structlog>=25.5.0",
    "psutil>=7.2.2",
]

[project.scripts]
alphaswarm = "alphaswarm:main"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24.0",
    "ruff",
    "mypy",
]

[build-system]
requires = ["uv_build>=0.11.0,<0.12"]
build-backend = "uv_build"

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "ANN", "B", "SIM"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
```

### Bracket Config Definitions (All 10)

```python
# Source: PROJECT_SPEC.md + CONTEXT.md
DEFAULT_BRACKETS: list[BracketConfig] = [
    BracketConfig(
        bracket_type=BracketType.QUANTS,
        display_name="Quants",
        count=10,
        risk_profile=0.4,
        temperature=0.3,
        system_prompt_template="You are a quantitative analyst. ...",
        influence_weight_base=0.7,
    ),
    BracketConfig(
        bracket_type=BracketType.DEGENS,
        display_name="Degens",
        count=20,
        risk_profile=0.95,
        temperature=1.2,
        system_prompt_template="You are a high-leverage degen trader. ...",
        influence_weight_base=0.3,
    ),
    BracketConfig(
        bracket_type=BracketType.SOVEREIGNS,
        display_name="Sovereigns",
        count=10,
        risk_profile=0.15,
        temperature=0.4,
        system_prompt_template="You are a sovereign wealth fund manager. ...",
        influence_weight_base=0.9,
    ),
    BracketConfig(
        bracket_type=BracketType.MACRO,
        display_name="Macro",
        count=10,
        risk_profile=0.35,
        temperature=0.5,
        system_prompt_template="You are a macro strategist focused on geopolitics. ...",
        influence_weight_base=0.6,
    ),
    BracketConfig(
        bracket_type=BracketType.SUITS,
        display_name="Suits",
        count=10,
        risk_profile=0.2,
        temperature=0.3,
        system_prompt_template="You are an institutional portfolio manager. ...",
        influence_weight_base=0.8,
    ),
    BracketConfig(
        bracket_type=BracketType.INSIDERS,
        display_name="Insiders",
        count=10,
        risk_profile=0.5,
        temperature=0.6,
        system_prompt_template="You are an industry insider with deep sector knowledge. ...",
        influence_weight_base=0.75,
    ),
    BracketConfig(
        bracket_type=BracketType.AGENTS,
        display_name="Agents",
        count=15,
        risk_profile=0.6,
        temperature=0.1,
        system_prompt_template="You are an autonomous trading algorithm. ...",
        influence_weight_base=0.5,
    ),
    BracketConfig(
        bracket_type=BracketType.DOOM_POSTERS,
        display_name="Doom-Posters",
        count=5,
        risk_profile=0.8,
        temperature=1.0,
        system_prompt_template="You are a perma-bear short-seller. ...",
        influence_weight_base=0.4,
    ),
    BracketConfig(
        bracket_type=BracketType.POLICY_WONKS,
        display_name="Policy Wonks",
        count=5,
        risk_profile=0.25,
        temperature=0.4,
        system_prompt_template="You are a regulatory and policy analyst. ...",
        influence_weight_base=0.65,
    ),
    BracketConfig(
        bracket_type=BracketType.WHALES,
        display_name="Whales",
        count=5,
        risk_profile=0.3,
        temperature=0.5,
        system_prompt_template="You are a deep-value whale investor. ...",
        influence_weight_base=0.85,
    ),
]
# Total: 10+20+10+10+10+10+15+5+5+5 = 100 agents
```

### Total Agent Count Validator

```python
# Source: Pydantic v2 docs model_validator
from pydantic import model_validator

class AppSettings(BaseSettings):
    # ... fields ...

    @model_validator(mode="after")
    def validate_agent_count(self) -> "AppSettings":
        """Ensure bracket agent counts sum to exactly 100."""
        total = sum(b.count for b in self.brackets)
        if total != 100:
            raise ValueError(
                f"Bracket agent counts must sum to 100, got {total}"
            )
        return self
```

### ResourceGovernor Interface Stub (Phase 1 Only)

```python
# Source: CONTEXT.md locked decision -- stub only, full impl Phase 3
import asyncio
from typing import Protocol

class ResourceGovernorProtocol(Protocol):
    """Interface contract for ResourceGovernor. Full impl in Phase 3."""
    async def acquire(self) -> None: ...
    def release(self) -> None: ...
    async def start_monitoring(self) -> None: ...
    async def stop_monitoring(self) -> None: ...
    @property
    def current_limit(self) -> int: ...
    @property
    def active_count(self) -> int: ...

class ResourceGovernor:
    """Stub ResourceGovernor for Phase 1. No-op implementation."""

    def __init__(self, baseline_parallel: int = 8) -> None:
        self._baseline = baseline_parallel
        self._current_limit = baseline_parallel

    async def acquire(self) -> None:
        pass  # No-op in Phase 1

    def release(self) -> None:
        pass  # No-op in Phase 1

    async def start_monitoring(self) -> None:
        pass  # Full psutil monitoring in Phase 3

    async def stop_monitoring(self) -> None:
        pass

    @property
    def current_limit(self) -> int:
        return self._current_limit

    @property
    def active_count(self) -> int:
        return 0

    async def __aenter__(self) -> "ResourceGovernor":
        await self.acquire()
        return self

    async def __aexit__(self, *args) -> None:
        self.release()
```

### StateStore Interface Stub (Phase 1 Only)

```python
# Source: CONTEXT.md + ARCHITECTURE.md -- interface only
from dataclasses import dataclass, field
from typing import Any

@dataclass
class StateSnapshot:
    """Immutable snapshot for TUI consumption. Full fields added in Phase 9."""
    phase: str = "idle"
    round_num: int = 0
    agent_count: int = 100

class StateStore:
    """Stub StateStore for Phase 1. Full implementation in Phase 9."""

    def snapshot(self) -> StateSnapshot:
        return StateSnapshot()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| python-dotenv + manual parsing | pydantic-settings v2 BaseSettings | 2023 (pydantic v2) | Built-in validation, type coercion, nested models via env delimiter |
| logging.basicConfig + JSON formatter | structlog with JSONRenderer | 2023+ (structlog 23.x) | Context vars, async methods, processor chains, zero-config JSON |
| poetry / pip-tools | uv | 2024-2025 | 10-100x faster, lockfile support, Python version management |
| setup.py / setup.cfg | pyproject.toml PEP 621 | 2022+ | Single config file, standardized metadata, build backend agnostic |

**Deprecated/outdated:**
- `pydantic.BaseSettings` (v1): Moved to separate `pydantic-settings` package in v2
- `logging.config.dictConfig` for JSON: structlog's processor chain is more composable
- `setup.py`: Use pyproject.toml for all new projects
- `poetry`: uv is the clear winner for new Python projects in 2026

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | Package management | -- NOT INSTALLED | -- | Install via `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python 3.11+ | Runtime | Yes | 3.11.5 at /usr/local/bin/python3.11, 3.13.1 at /opt/homebrew/bin/python3.13 | uv can install Python 3.11+ automatically |
| Ollama | LLM inference (Phase 2+) | Yes (not running) | 0.18.1 | Not needed for Phase 1 |
| Docker | Neo4j (Phase 4+) | -- NOT INSTALLED | -- | Not needed for Phase 1 |
| Node.js | Not required | Yes | v23.6.0 | N/A |

**Missing dependencies with no fallback:**
- **uv:** MUST be installed before Phase 1 can begin. Install command: `curl -LsSf https://astral.sh/uv/install.sh | sh`

**Missing dependencies with fallback:**
- **Docker:** Not needed until Phase 4 (Neo4j). Can be installed later.
- **Default Python (3.10.14):** The system default Python is 3.10, but 3.11.5 and 3.13.1 are both available. uv's `.python-version` file will pin the project to 3.11+.

**CRITICAL NOTE:** The first task in the plan MUST install `uv` and configure the project to use Python 3.11+. The `.python-version` file should specify `3.11` to ensure uv selects the correct interpreter.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest >= 8.0 + pytest-asyncio >= 0.24.0 |
| Config file | none -- Wave 0 must create `pyproject.toml` `[tool.pytest.ini_options]` section |
| Quick run command | `uv run pytest tests/ -x -q` |
| Full suite command | `uv run pytest tests/ -v --tb=short` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CONF-01 | Pydantic settings loads from defaults + env vars, validates | unit | `uv run pytest tests/test_config.py::test_settings_defaults -x` | -- Wave 0 |
| CONF-01 | Pydantic settings rejects invalid values | unit | `uv run pytest tests/test_config.py::test_settings_validation_errors -x` | -- Wave 0 |
| CONF-02 | All 10 brackets defined with correct counts totaling 100 | unit | `uv run pytest tests/test_config.py::test_bracket_definitions -x` | -- Wave 0 |
| CONF-02 | Agent personas generated with distinct IDs and correct bracket assignment | unit | `uv run pytest tests/test_types.py::test_persona_generation -x` | -- Wave 0 |
| INFRA-11 | structlog outputs JSON-formatted log lines | unit | `uv run pytest tests/test_logging.py::test_json_output -x` | -- Wave 0 |
| INFRA-11 | Correlation ID context binding appears in log output | unit | `uv run pytest tests/test_logging.py::test_correlation_binding -x` | -- Wave 0 |
| SC-1 | `uv run python -m alphaswarm` starts without errors and prints banner | smoke | `uv run python -m alphaswarm` (exit code 0) | -- Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/ -x -q`
- **Per wave merge:** `uv run pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/conftest.py` -- shared fixtures (clean env vars, temp config)
- [ ] `tests/test_config.py` -- covers CONF-01, CONF-02
- [ ] `tests/test_types.py` -- covers CONF-02 (persona generation)
- [ ] `tests/test_logging.py` -- covers INFRA-11
- [ ] `pyproject.toml` `[tool.pytest.ini_options]` section -- `asyncio_mode = "auto"`
- [ ] Framework install: `uv add --dev pytest pytest-asyncio`

## Open Questions

1. **System prompt template content**
   - What we know: Each bracket needs a distinct system prompt template that embeds the archetype's personality, risk bias, and decision heuristics.
   - What's unclear: The exact prompt text for each of the 10 brackets. Phase 1 needs placeholder templates; Phase 5 will refine them for actual LLM inference.
   - Recommendation: Write short (~3 sentence) placeholder templates in Phase 1 that capture the archetype's core personality. Mark them with `# TODO: Refine for Phase 5 inference quality` comments.

2. **Bracket risk_profile / temperature / influence_weight_base calibration**
   - What we know: Each bracket needs distinct numerical values for these parameters. The CONTEXT.md lists the basics.
   - What's unclear: Whether the specific numerical values produce meaningfully different agent behaviors during inference.
   - Recommendation: Set reasonable initial values based on archetype descriptions (Degens = high risk/temp, Sovereigns = low risk/temp). Document that these are "initial calibration" values subject to tuning in Phase 5-6.

3. **Additional AgentPersona fields**
   - What we know: The required fields are: id, name, bracket, risk_profile, temperature, system_prompt_template, influence_weight_base.
   - What's unclear: Whether additional fields (e.g., `decision_bias`, `information_sources`, `reaction_speed`) are needed for simulation fidelity.
   - Recommendation: Start with the required fields only. Add fields in Phase 5 if prompt engineering reveals the need. Keep the frozen model minimal.

## Sources

### Primary (HIGH confidence)
- [pydantic-settings PyPI (v2.13.1)](https://pypi.org/project/pydantic-settings/) -- BaseSettings, env_nested_delimiter, .env support
- [pydantic-settings official docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) -- Nested models, validation, env mapping
- [structlog PyPI (v25.5.0)](https://pypi.org/project/structlog/) -- Version verification
- [structlog contextvars docs](https://www.structlog.org/en/stable/contextvars.html) -- bind_contextvars, merge_contextvars, async safety
- [structlog getting started](https://www.structlog.org/en/stable/getting-started.html) -- Configuration, JSONRenderer, processor chain
- [uv project creation docs](https://docs.astral.sh/uv/concepts/projects/init/) -- `--package` flag, directory structure, pyproject.toml
- [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/) -- macOS install methods
- [psutil PyPI (v7.2.2)](https://pypi.org/project/psutil/) -- Version verification
- [pydantic PyPI (v2.12.5)](https://pypi.org/project/pydantic/) -- Version verification
- [uv __main__.py issue #16764](https://github.com/astral-sh/uv/issues/16764) -- Must use `uv run python -m package`, not `uv run ./package`

### Secondary (MEDIUM confidence)
- [structlog async logging guide (johal.in)](https://johal.in/structlog-contextvars-python-async-logging-2026/) -- Async patterns verified against official docs
- [uv pyproject.toml setup (bitdoze)](https://www.bitdoze.com/uv-get-start/) -- Project setup flow verified against official docs

### Tertiary (LOW confidence)
- None. All findings verified against primary sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all package versions verified on PyPI, all APIs verified in official docs
- Architecture: HIGH -- patterns drawn from official Pydantic/structlog docs and locked CONTEXT.md decisions
- Pitfalls: HIGH -- all pitfalls verified through official docs or confirmed GitHub issues (uv #16764)

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable libraries, 30-day validity)
