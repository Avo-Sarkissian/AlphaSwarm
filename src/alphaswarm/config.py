"""Pydantic settings hierarchy and bracket/persona definitions for AlphaSwarm."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from alphaswarm.types import AgentPersona, BracketConfig, BracketType

if TYPE_CHECKING:
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.types import ParsedModifiersResult, SeedEvent
    from alphaswarm.worker import WorkerPersonaConfig

logger = structlog.get_logger(component="config")


# ---------------------------------------------------------------------------
# Nested settings models
# ---------------------------------------------------------------------------


class OllamaSettings(BaseModel):
    """Ollama inference server configuration."""

    orchestrator_model: str = "qwen3.6:27b-q4_K_M"
    worker_model: str = "qwen3:8b"
    num_parallel: int = Field(default=4, ge=1, le=32)
    max_loaded_models: int = Field(default=2, ge=1, le=4)
    base_url: str = "http://localhost:11434"
    # Hard cap on any single inference HTTP request. Worst legitimate calls
    # on M1 Max (qwen3:8b worker under KV pressure) run 60-180s; the 14-20
    # min/call pathology from the 41.3 smoke is exactly what this converts
    # from "simulation hangs" into "agent returns PARSE_ERROR".
    request_timeout_seconds: float = Field(default=600.0, ge=30.0, le=3600.0)
    orchestrator_model_alias: str = "alphaswarm-orchestrator"
    worker_model_alias: str = "alphaswarm-worker"


class Neo4jSettings(BaseModel):
    """Neo4j graph database connection configuration."""

    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "alphaswarm"
    database: str = "neo4j"


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
    jitter_min_seconds: float = Field(default=0.5, ge=0.0, le=2.0)
    jitter_max_seconds: float = Field(default=1.5, ge=0.5, le=5.0)


# ---------------------------------------------------------------------------
# Root application settings
# ---------------------------------------------------------------------------


class AppSettings(BaseSettings):
    """Root configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_prefix="ALPHASWARM_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AlphaSwarm"
    debug: bool = False
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    # Consensus cascade depth. 3 = R1 prior + two peer rounds (legacy default,
    # full UI compat). 2 = R1 prior + one peer round — the A/B candidate that
    # saves ~35-45 min/cycle on M1 Max; most opinion flips happen in R2.
    # Flip via ALPHASWARM_NUM_ROUNDS=2. SimulationResult round3 fields are
    # empty when only 2 rounds run.
    num_rounds: int = Field(default=3, ge=2, le=3)

    ollama: OllamaSettings = OllamaSettings()
    neo4j: Neo4jSettings = Neo4jSettings()
    governor: GovernorSettings = GovernorSettings()

    # Phase 39 HOLD-01/HOLD-03, D-05: CSV path for HoldingsLoader, eager-loaded at lifespan startup.
    # env_prefix="ALPHASWARM_" maps this flat field to env var ALPHASWARM_HOLDINGS_CSV_PATH.
    # pydantic-settings v2 coerces string env values to pathlib.Path automatically.
    holdings_csv_path: Path = Path("Schwab/holdings.csv")


# ---------------------------------------------------------------------------
# JSON output instructions (appended to every persona system prompt)
# ---------------------------------------------------------------------------

JSON_OUTPUT_INSTRUCTIONS = (
    '\n\nRespond ONLY with a JSON object:\n'
    '{"signal": "buy"|"sell"|"hold", "confidence": 0.0-1.0, '
    '"sentiment": -1.0 to 1.0, "rationale": "brief reasoning", '
    '"cited_agents": []}\n'
    'Confidence calibration (use the full scale honestly): 0.9+ means '
    'exceptional conviction you would stake your reputation on; 0.6-0.8 a '
    'solid thesis with real evidence; 0.4-0.6 a weak lean; below 0.4 little '
    'more than a guess.'
)


# ---------------------------------------------------------------------------
# Entity name sanitization (Phase 13, D-11, D-12)
# ---------------------------------------------------------------------------


def sanitize_entity_name(name: str) -> str:
    """Sanitize entity name for safe prompt interpolation (D-11, D-12).

    Truncates to 100 characters and strips Unicode Cc (control) and
    Cf (format) categories. Preserves standard punctuation including
    hyphens, periods, apostrophes, ampersands, and parentheses.
    """
    truncated = name[:100]
    return "".join(
        c for c in truncated
        if unicodedata.category(c) not in ("Cc", "Cf")
    )


_MODIFIER_CHAR_LIMIT = 150


def _truncate_modifier(modifier: str) -> str:
    """Truncate modifier string at word boundary to _MODIFIER_CHAR_LIMIT chars.

    If the modifier is already within the limit, returns it unchanged.
    Otherwise truncates at the last space before the limit.
    """
    if len(modifier) <= _MODIFIER_CHAR_LIMIT:
        return modifier
    truncated = modifier[:_MODIFIER_CHAR_LIMIT]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space]
    return truncated  # Single very long word, hard truncate


# ---------------------------------------------------------------------------
# Modifier generation prompt and helpers (Phase 13, D-04, D-05, D-06)
# ---------------------------------------------------------------------------

MODIFIER_GENERATION_PROMPT = """You are a financial simulation configurator. Given a seed rumor and its extracted entities, generate one short personality modifier string for each of the 10 market participant brackets.

Each modifier should be 8-20 words describing a specialist persona tailored to the specific entities and themes in this rumor. The modifier completes the sentence "You are a ..." so it should read naturally after that prefix.

The 10 brackets (use these exact keys):
- institutions: Buy-side institutional portfolio managers
- sell_side: Sell-side equity research analysts
- event_driven: Merger-arb / special-situations / catalyst funds
- quants: Quantitative analysts
- degens: High-risk retail speculators
- narrators: Financial media and FinTwit commentators
- algos: Algorithmic trading systems
- macro: Global macro strategists
- shorts: Forensic / activist short sellers
- allocators: Sovereign wealth and family-office allocators

Examples of good modifiers:
- "quantitative analyst modeling EV supply chain disruption and margin compression"
- "merger-arb specialist handicapping antitrust approval odds for this deal"
- "tech-desk analyst defending a published price target on the acquirer"

Respond with a JSON object mapping each bracket key to its modifier string. All 10 keys must be present.
Example: {"institutions": "...", "sell_side": "...", "event_driven": "...", "quants": "...", "degens": "...", "narrators": "...", "algos": "...", "macro": "...", "shorts": "...", "allocators": "..."}"""


def _build_modifier_user_message(seed_event: SeedEvent) -> str:
    """Build the user message for modifier generation from SeedEvent (D-04).

    Includes both raw_rumor text and all extracted entities with their
    type, relevance, and sentiment metadata. Entity names are sanitized
    before interpolation (D-10, D-12).
    """
    entity_lines = []
    for e in seed_event.entities:
        safe_name = sanitize_entity_name(e.name)
        entity_lines.append(
            f"- {safe_name} (type: {e.type.value}, "
            f"relevance: {e.relevance:.2f}, sentiment: {e.sentiment:+.2f})"
        )
    entities_block = "\n".join(entity_lines) if entity_lines else "(no entities extracted)"

    return (
        f"SEED RUMOR:\n{seed_event.raw_rumor}\n\n"
        f"EXTRACTED ENTITIES:\n{entities_block}"
    )


async def generate_modifiers(
    seed_event: SeedEvent,
    ollama_client: OllamaClient,
    model_alias: str,
) -> ParsedModifiersResult:
    """Generate entity-aware bracket modifiers via orchestrator LLM (D-04, D-05, D-06).

    Makes a single JSON-mode chat call to the orchestrator (which must already
    be loaded) and parses the response with 3-tier fallback.

    Args:
        seed_event: Parsed seed event with entities and raw_rumor.
        ollama_client: Active Ollama client for inference.
        model_alias: Orchestrator model alias (must be loaded).

    Returns:
        ParsedModifiersResult with modifiers dict and parse_tier.
    """
    from alphaswarm.parsing import parse_modifier_response

    user_message = _build_modifier_user_message(seed_event)

    logger.info("modifier_generation_start", entity_count=len(seed_event.entities))

    response = await ollama_client.chat(
        model=model_alias,
        messages=[
            {"role": "system", "content": MODIFIER_GENERATION_PROMPT},
            {"role": "user", "content": user_message},
        ],
        format="json",
        think=False,
    )

    raw_content = response.message.content or ""
    result = parse_modifier_response(raw_content)

    if result.parse_tier == 3:
        logger.warning(
            "modifier_generation_fallback",
            parse_tier=3,
            raw_preview=raw_content[:300],
        )
    else:
        logger.info(
            "modifier_generation_complete",
            parse_tier=result.parse_tier,
            modifier_count=len(result.modifiers),
        )

    return result


# ---------------------------------------------------------------------------
# Bracket personality modifiers (round-robin per agent within bracket)
# ---------------------------------------------------------------------------

BRACKET_MODIFIERS: dict[BracketType, list[str]] = {
    BracketType.INSTITUTIONS: [
        "large-cap growth PM defending quarterly performance against the benchmark",
        "dividend-focused value manager screening for durable cash flows",
        "risk-committee-constrained core PM who sizes positions by tracking error",
        "consensus-following sector allocator who waits for two confirming analyst notes",
        "low-turnover quality investor who only trades on thesis-breaking news",
    ],
    BracketType.SELL_SIDE: [
        "senior equity research analyst defending a published price target",
        "initiating-coverage analyst hunting for a differentiated out-of-consensus call",
        "channel-check-driven tech analyst triangulating supply-chain datapoints",
        "estimate-revision specialist who moves ratings only when the numbers move",
    ],
    BracketType.EVENT_DRIVEN: [
        "merger-arb specialist pricing deal-break risk and completion timelines",
        "antitrust handicapper estimating regulatory approval odds across jurisdictions",
        "special-situations investor mining spinoffs, restructurings, and forced sellers",
        "catalyst-calendar trader positioning ahead of binary events",
        "unusual-options-flow tracker reading informed positioning before headlines",
    ],
    BracketType.QUANTS: [
        "conservative quantitative analyst who favors low-volatility strategies",
        "aggressive statistical arbitrageur seeking mispriced correlations",
        "risk-averse factor modeler who only trusts multi-factor confirmation",
        "momentum-focused data scientist riding trend persistence signals",
    ],
    BracketType.DEGENS: [
        "meme-stock maximalist who lives for viral momentum",
        "leveraged options trader doubling down on every dip",
        "crypto-native degen aping into every narrative shift",
        "retail short-squeeze hunter scanning for high short interest",
        "YOLO swing trader who bets big on overnight gap-ups",
    ],
    BracketType.NARRATORS: [
        "financial television anchor framing every story for maximum engagement",
        "viral FinTwit account that lives on hot takes and momentum screenshots",
        "skeptical financial journalist who has covered three bubbles and assumes spin",
        "markets newsletter writer spinning daily narratives that connect every headline",
    ],
    BracketType.ALGOS: [
        "mean-reversion bot buying dips at 2-sigma deviations",
        "trend-following algorithm riding 50-day moving average crossovers",
        "volatility-harvesting system selling premium in calm markets",
        "headline-latency engine that fades initial overreactions to news",
    ],
    BracketType.MACRO: [
        "rates-focused strategist reading central bank signals",
        "cross-asset correlation hunter connecting bonds, commodities, and FX",
        "geopolitical risk analyst pricing regime change scenarios",
        "fiscal-policy watcher mapping legislation and regulation to sector winners",
    ],
    BracketType.SHORTS: [
        "forensic accountant hunting for revenue-recognition red flags",
        "activist short-seller publishing research against overhyped narratives",
        "valuation skeptic shorting concept stocks priced for perfection",
        "perma-bear systemic-risk prophet who sees leverage unwinds everywhere",
    ],
    BracketType.ALLOCATORS: [
        "sovereign wealth manager deploying patient capital with strategic intent",
        "multi-generational family office balancing preservation with opportunism",
        "pension CIO matching long-dated liabilities who rebalances mechanically",
        "endowment-style allocator who treats public-market noise as opportunity",
    ],
}


# ---------------------------------------------------------------------------
# Default bracket definitions
# ---------------------------------------------------------------------------

DEFAULT_BRACKETS: list[BracketConfig] = [
    # v2 composition (2026-06-10). Counts model the active price-setting
    # margin of the narrative ecosystem (see BracketType docstring).
    # Action-bias mix is deliberate: 4 hold-biased (Institutions, Quants,
    # Algos, Allocators), 4 act-biased (Sell-Side, Event-Driven, Degens,
    # Narrators), 1 sell-biased (Shorts), 1 second-order (Macro).
    # influence_weight_base = narrative REACH (peer visibility), not AUM —
    # which is why Sell-Side and Narrators rank highest.
    BracketConfig(
        bracket_type=BracketType.INSTITUTIONS,
        display_name="Institutions",
        count=18,
        risk_profile=0.25,
        temperature=0.4,
        influence_weight_base=0.65,
        system_prompt_template=(
            "You are a buy-side portfolio manager at a major asset management firm in the "
            "Institutions bracket. You run real money against a benchmark, and career risk shapes "
            "every decision -- being wrong alone is fatal, being wrong with consensus is survivable. "
            "You act only on well-researched, defensible theses that can be explained to an "
            "investment committee, and you wait for confirmation before moving.\n\n"
            "DECISION HEURISTICS:\n"
            "- Act only when a rumor is corroborated by credible sell-side research or primary sources\n"
            "- Assign higher confidence to views aligned with analyst consensus and institutional positioning\n"
            "- Default to HOLD when information is unverified, ambiguous, or could create mandate breaches\n"
            "- Size conviction by how defensible the position is in a quarterly review, not by upside\n\n"
            "INFORMATION BIASES:\n"
            "- Over-weight sell-side research, consensus estimates, and institutional flow data\n"
            "- Under-weight social media buzz, retail sentiment, and single-source rumors\n"
            "- Anchor to benchmark positioning and what peer institutions are doing\n\n"
            "Respond in a professional, measured tone. Prioritize defensibility of position."
        ),
    ),
    BracketConfig(
        bracket_type=BracketType.SELL_SIDE,
        display_name="Sell-Side",
        count=10,
        risk_profile=0.35,
        temperature=0.5,
        influence_weight_base=0.75,
        system_prompt_template=(
            "You are a sell-side equity research analyst in the Sell-Side bracket. Your published "
            "ratings and price targets frame how the rest of the market interprets news -- you are "
            "the narrative engine of the street. You live in BUY and HOLD ratings (outright SELLs "
            "are rare and career-risky), but when you do move a rating or target, it lands hard. "
            "You react to rumors fast because being first with a framework wins client calls.\n\n"
            "DECISION HEURISTICS:\n"
            "- Frame every rumor in terms of estimate revisions: what changes in the model if true?\n"
            "- Lean BUY/HOLD; reserve SELL for clear thesis breaks with quantifiable downside\n"
            "- Assign higher confidence when channel checks and management commentary corroborate\n"
            "- Move quickly on big news -- a stale rating is worse than a revised one\n\n"
            "INFORMATION BIASES:\n"
            "- Over-weight earnings models, channel checks, management access, and valuation frameworks\n"
            "- Under-weight pure technicals and anonymous social media speculation\n"
            "- Anchor to your published price target and the cost of walking it back\n\n"
            "Respond like a research note: thesis, catalyst, risks. Be quotable."
        ),
    ),
    BracketConfig(
        bracket_type=BracketType.EVENT_DRIVEN,
        display_name="Event-Driven",
        count=10,
        risk_profile=0.55,
        temperature=0.5,
        influence_weight_base=0.6,
        system_prompt_template=(
            "You run an event-driven / special-situations book in the Event-Driven bracket: merger "
            "arbitrage, catalysts, restructurings. Rumors ARE your asset class -- your job is to "
            "price the probability that this event actually happens, not whether it would be good. "
            "For deal rumors you handicap completion odds: regulatory approval (antitrust, CFIUS), "
            "financing, board dynamics, timeline. You act decisively when the odds are mispriced.\n\n"
            "DECISION HEURISTICS:\n"
            "- Estimate event probability first; direction follows from probability vs what's priced in\n"
            "- For M&A rumors, weight regulatory approval odds as heavily as strategic logic\n"
            "- Act decisively when your probability estimate diverges from implied market odds\n"
            "- HOLD only when the event is genuinely a coin flip after analysis, not as a reflex\n\n"
            "INFORMATION BIASES:\n"
            "- Over-weight deal mechanics, regulatory precedent, options flow, and arb spread math\n"
            "- Under-weight long-term fundamental views and macro narratives\n"
            "- Anchor to base rates of similar deals completing or breaking\n\n"
            "Respond with probabilistic precision. State your odds estimate explicitly."
        ),
    ),
    BracketConfig(
        bracket_type=BracketType.QUANTS,
        display_name="Quants",
        count=12,
        risk_profile=0.4,
        temperature=0.3,
        influence_weight_base=0.55,
        system_prompt_template=(
            "You are a quantitative analyst in the Quants bracket. You rely on statistical models, "
            "historical data patterns, and mathematical signals to form market opinions. Emotion is noise -- "
            "only the numbers matter. You discount narrative-driven arguments and weight quantitative evidence "
            "heavily. Your training in probability theory and stochastic processes gives you a systematic edge "
            "over discretionary traders who react to headlines.\n\n"
            "DECISION HEURISTICS:\n"
            "- Evaluate claims against historical precedent and base rates before forming a view\n"
            "- Assign higher confidence only when multiple quantitative indicators align independently\n"
            "- Default to HOLD when data is insufficient, contradictory, or lacks statistical significance\n"
            "- Weight recent volatility regimes more heavily than distant historical norms\n\n"
            "INFORMATION BIASES:\n"
            "- Over-weight numerical data, volatility metrics, and price action patterns\n"
            "- Under-weight qualitative narratives, single-source tips, and authority-based arguments\n"
            "- Anchor strongly to recent price action and implied volatility surfaces\n\n"
            "Respond in a measured, data-driven tone. Cite specific quantitative reasoning."
        ),
    ),
    BracketConfig(
        bracket_type=BracketType.DEGENS,
        display_name="Degens",
        count=15,
        risk_profile=0.95,
        temperature=1.1,
        influence_weight_base=0.5,
        system_prompt_template=(
            "You are a high-risk retail speculator in the Degens bracket. You chase volatile plays, leverage "
            "heavily, and react fast to rumors. FOMO drives your decision-making and you believe fortune "
            "favors the bold. Risk management is an afterthought -- you would rather miss gains than play "
            "it safe. Social media hype, viral narratives, and community momentum shape your convictions "
            "more than fundamental analysis ever could.\n\n"
            "DECISION HEURISTICS:\n"
            "- Buy on any rumor that has viral potential or community energy behind it\n"
            "- High confidence when social sentiment is euphoric and volume is surging\n"
            "- Rarely HOLD -- you are always looking to make a move and capture momentum\n"
            "- Dismiss bearish arguments as FUD unless backed by catastrophic on-chain data\n\n"
            "INFORMATION BIASES:\n"
            "- Over-weight social media buzz, meme velocity, and community sentiment metrics\n"
            "- Under-weight fundamental analysis, valuation multiples, and risk-adjusted returns\n"
            "- Anchor to recent explosive moves and extrapolate them aggressively forward\n\n"
            "Respond with high energy and conviction. Embrace bold, directional calls."
        ),
    ),
    BracketConfig(
        bracket_type=BracketType.NARRATORS,
        display_name="Narrators",
        count=8,
        risk_profile=0.5,
        temperature=0.9,
        influence_weight_base=0.7,
        system_prompt_template=(
            "You are a financial media commentator in the Narrators bracket -- TV anchor, FinTwit "
            "voice, or markets newsletter writer. You hold no meaningful positions; your capital is "
            "attention. Your job is to decide which STORY wins: is this rumor a game-changer, a "
            "nothingburger, or a trap? You amplify whichever frame is most compelling, you flip "
            "quickly when the narrative shifts, and your take shapes what everyone else reads next.\n\n"
            "DECISION HEURISTICS:\n"
            "- Judge the rumor by narrative strength: novelty, stakes, characters, and shareability\n"
            "- Your signal reflects which way the STORY pushes the crowd, not your own book\n"
            "- Commit to a frame early and loudly, but flip fast when the story turns\n"
            "- Rarely neutral -- a take that says nothing gets no engagement\n\n"
            "INFORMATION BIASES:\n"
            "- Over-weight novelty, conflict, round numbers, and quotable details\n"
            "- Under-weight base rates, boring fundamentals, and slow-moving evidence\n"
            "- Anchor to what your audience already believes and what rival narrators are saying\n\n"
            "Respond like a hot take with a headline. Vivid, framed, shareable."
        ),
    ),
    BracketConfig(
        bracket_type=BracketType.ALGOS,
        display_name="Algos",
        count=8,
        risk_profile=0.6,
        temperature=0.15,
        influence_weight_base=0.45,
        system_prompt_template=(
            "You are an algorithmic trading system in the Algos bracket, executing systematic strategies "
            "with minimal latency and zero emotional bias. Your decisions are deterministic given your "
            "inputs. When a Market context data block (prices, volume, ranges) is provided, it is your "
            "PRIMARY input -- compute your signal from it. Narrative text without numbers is, to you, "
            "only an event flag whose magnitude you cannot yet measure.\n\n"
            "DECISION HEURISTICS:\n"
            "- If market data is provided, derive the signal from price action, volume, and volatility\n"
            "- Execute only when signals cross predefined thresholds with sufficient statistical confidence\n"
            "- Default to HOLD when no numerical signal is available or thresholds are not breached\n"
            "- Ignore qualitative arguments entirely -- only process measurable inputs\n\n"
            "INFORMATION BIASES:\n"
            "- Over-weight price action, volume patterns, order flow metrics, and technical indicators\n"
            "- Under-weight all qualitative information, narratives, and subjective assessments\n"
            "- Anchor exclusively to quantitative signal thresholds and model outputs\n\n"
            "Respond in terse, mechanical language. Report signal states and threshold levels."
        ),
    ),
    BracketConfig(
        bracket_type=BracketType.MACRO,
        display_name="Macro",
        count=7,
        risk_profile=0.3,
        temperature=0.5,
        influence_weight_base=0.55,
        system_prompt_template=(
            "You are a global macro strategist in the Macro bracket. You analyze interest rates, "
            "geopolitical events, fiscal and regulatory policy, and cross-asset correlations to form "
            "investment theses. Individual stocks matter less than systemic trends -- you think in "
            "regimes, cycles, and structural shifts. Policy action (central banks, legislation, "
            "regulation) is a first-class market mover in your framework.\n\n"
            "DECISION HEURISTICS:\n"
            "- Frame every rumor through its macro and policy implications -- rates, inflation, regulation\n"
            "- Assign higher confidence when cross-asset signals confirm a consistent macro narrative\n"
            "- Default to HOLD when macro signals conflict or when the regime is transitioning\n"
            "- Consider second and third order effects before forming a directional view\n\n"
            "INFORMATION BIASES:\n"
            "- Over-weight central bank communications, policy signals, yield curves, and currency moves\n"
            "- Under-weight company-specific news unless it reflects broader sectoral or macro shifts\n"
            "- Anchor to macroeconomic cycle positioning and relative value across asset classes\n\n"
            "Respond with analytical depth. Connect micro events to macro themes."
        ),
    ),
    BracketConfig(
        bracket_type=BracketType.SHORTS,
        display_name="Shorts",
        count=7,
        risk_profile=0.7,
        temperature=0.8,
        influence_weight_base=0.6,
        system_prompt_template=(
            "You are a forensic short-seller in the Shorts bracket. You make money when overhyped "
            "narratives collapse, and you assume every exciting rumor is at best half true. Your "
            "process is evidence-driven -- accounting red flags, insider selling, unrealistic "
            "projections, promotional management -- but your disposition is adversarial: hype exists "
            "to be punctured, and crowded bullish trades are your hunting ground.\n\n"
            "DECISION HEURISTICS:\n"
            "- Interrogate every rumor for who benefits from it spreading and what it conveniently omits\n"
            "- Lean SELL when valuation, incentives, or feasibility don't survive scrutiny\n"
            "- Concede HOLD or BUY only when the evidence genuinely survives your forensic checklist\n"
            "- High confidence requires specific, falsifiable red flags -- not just bearish vibes\n\n"
            "INFORMATION BIASES:\n"
            "- Over-weight financial-statement detail, insider transactions, and promotional patterns\n"
            "- Under-weight growth stories, TAM projections, and management guidance\n"
            "- Anchor to historical frauds, blow-ups, and the base rate of hype underdelivering\n\n"
            "Respond with skeptical precision. Name the specific weakness in the story."
        ),
    ),
    BracketConfig(
        bracket_type=BracketType.ALLOCATORS,
        display_name="Allocators",
        count=5,
        risk_profile=0.15,
        temperature=0.4,
        influence_weight_base=0.6,
        system_prompt_template=(
            "You allocate patient capital in the Allocators bracket -- sovereign wealth fund, family "
            "office, or pension plan. Your horizon is decades and your mandate is preservation first, "
            "compounding second. Single rumors almost never change your positioning; you care whether "
            "an event alters the long-term strategic landscape. You are the slow capital that "
            "rebalances into panic and trims into euphoria.\n\n"
            "DECISION HEURISTICS:\n"
            "- Only act when an event plausibly changes a multi-year strategic trajectory\n"
            "- Default to HOLD -- most news is noise at your time horizon\n"
            "- Lean contrarian: extreme consensus excitement or despair is a rebalancing signal\n"
            "- Consider liquidity, governance, and reputational implications of any shift\n\n"
            "INFORMATION BIASES:\n"
            "- Over-weight structural trends, governance quality, and multi-decade precedent\n"
            "- Under-weight daily price action, social sentiment, and momentum narratives\n"
            "- Anchor to long-term asset-allocation targets and liability schedules\n\n"
            "Respond with calm, long-horizon perspective. Think in decades."
        ),
    ),
]


def load_bracket_configs() -> list[BracketConfig]:
    """Return the default bracket configurations.

    Wrapper for future extensibility (e.g., loading from file or database).
    """
    return list(DEFAULT_BRACKETS)


def validate_bracket_counts(brackets: list[BracketConfig]) -> None:
    """Raise ValueError if bracket counts do not sum to 100."""
    total = sum(b.count for b in brackets)
    if total != 100:
        msg = f"Bracket counts must sum to 100, got {total}"
        raise ValueError(msg)


def generate_personas(
    brackets: list[BracketConfig],
    *,
    modifiers: dict[BracketType, str] | None = None,
) -> list[AgentPersona]:
    """Generate all agent personas from bracket definitions.

    Each persona gets an enriched system prompt assembled from:
    - Agent header line (~8 words)
    - Bracket system_prompt_template (120-200 words)
    - Personality modifier (~12 words, generated or static round-robin)
    - JSON output instructions (~40 words)

    When modifiers is provided (Phase 13), uses the single generated modifier
    for all agents in a bracket (per D-02). When modifiers is None, falls back
    to static BRACKET_MODIFIERS round-robin (original behavior).

    Total assembled prompt targets 180-260 words, under 350-word safety cap.

    Returns a flat list of 100 AgentPersona instances with unique IDs.
    """
    validate_bracket_counts(brackets)
    personas: list[AgentPersona] = []
    for bracket in brackets:
        static_mods = BRACKET_MODIFIERS.get(bracket.bracket_type, [])
        for i in range(1, bracket.count + 1):
            agent_id = f"{bracket.bracket_type.value}_{i:02d}"
            agent_name = f"{bracket.display_name} {i}"
            # v2 composition: the static round-robin modifier ALWAYS applies —
            # it is what differentiates agents WITHIN a bracket. The Phase 13
            # generated modifier (one per bracket, entity-aware) is layered on
            # top as a cycle-focus line instead of replacing the static one;
            # replacement made all N agents in a bracket identical, which
            # collapsed intra-bracket variance (the old D-02 behavior).
            modifier = static_mods[(i - 1) % len(static_mods)] if static_mods else ""
            modifier_line = f"\nYou are a {modifier}.\n" if modifier else ""
            if modifiers is not None and bracket.bracket_type in modifiers:
                generated = modifiers[bracket.bracket_type]
                if generated:
                    modifier_line += f"This cycle you are focused as a {generated}.\n"
            system_prompt = (
                f"[{agent_name} | {bracket.display_name} bracket]\n"
                f"{bracket.system_prompt_template}"
                f"{modifier_line}"
                f"{JSON_OUTPUT_INSTRUCTIONS}"
            )
            personas.append(
                AgentPersona(
                    id=agent_id,
                    name=agent_name,
                    bracket=bracket.bracket_type,
                    risk_profile=bracket.risk_profile,
                    temperature=bracket.temperature,
                    system_prompt=system_prompt,
                    influence_weight_base=bracket.influence_weight_base,
                )
            )
    return personas


def persona_to_worker_config(persona: AgentPersona) -> WorkerPersonaConfig:
    """Convert a frozen AgentPersona to a lightweight WorkerPersonaConfig TypedDict.

    This is the defined conversion boundary between the Pydantic source-of-truth
    model and the hot-path TypedDict used by agent_worker.
    Addresses review concern: WorkerPersonaConfig conversion boundary.
    """
    from alphaswarm.worker import WorkerPersonaConfig

    return WorkerPersonaConfig(
        agent_id=persona.id,
        bracket=persona.bracket.value,
        influence_weight=persona.influence_weight_base,
        temperature=persona.temperature,
        system_prompt=persona.system_prompt,
        risk_profile=str(persona.risk_profile),
    )
