# Stack Research: v2.0 Engine Depth

**Domain:** Multi-agent financial simulation -- post-simulation interviews, live graph memory, report generation, social interactions, dynamic personas
**Researched:** 2026-03-31
**Confidence:** HIGH (existing stack validated; additions are incremental)

## Scope

This document covers ONLY the stack additions and changes needed for v2.0 Engine Depth features. The validated v1 stack (Python 3.11+, asyncio, ollama >=0.6.1, neo4j >=5.28, textual >=8.1.1, pydantic, structlog, psutil, httpx, backoff) is NOT re-evaluated. See the original STACK.md research from 2026-03-24 for v1 rationale.

## Critical Finding: qwen3.5 Tool Calling Is Broken

**Impact:** REPORT-01 (ReACT report agent) cannot use Ollama's native tool calling with qwen3.5.

The Ollama tool calling pipeline sends Qwen 3 Hermes-style JSON tool schemas, but qwen3.5 was trained on the Qwen3-Coder XML format. This mismatch causes tool calls to be printed as text instead of executed, and unclosed `<think>` tags corrupt multi-turn conversations when thinking is enabled. A partial fix was merged (PR #14603, 2026-03-04) but community reports confirm tool calling still fails in production setups.

**Resolution:** Implement the ReACT report agent using prompt-based tool dispatching (Simon Willison pattern) instead of Ollama's native `tools=` parameter. The agent outputs structured `Action: tool_name: args` text, which Python code parses via regex and dispatches to registered Cypher query functions. This approach works with ANY model regardless of tool calling support, and is ~100 lines of code. The qwen3.5:32b orchestrator model is more than capable of following the ReACT prompt format.

**Confidence:** HIGH -- verified via GitHub issues #14493 and #14745, confirmed broken as of 2026-03-31.

## Recommended Stack Additions

### New Dependencies

| Library | Version | Purpose | Why Recommended | Feature |
|---------|---------|---------|-----------------|---------|
| Jinja2 | >=3.1.6 | Report template rendering | Standard Python template engine. Report sections (consensus summary, dissenter analysis, flip analysis) are templated markdown with data placeholders. Jinja2 handles conditionals, loops, and filters that f-strings cannot (e.g., iterating bracket summaries, conditional dissent sections). Mature, zero-CVE history, 3.1.6 released 2025-03-05. | REPORT-01, REPORT-02, REPORT-03 |
| aiofiles | >=24.1.0 | Async file I/O for report export | Report markdown must be written to disk without blocking the asyncio event loop. aiofiles wraps file I/O in a thread pool executor, providing `async with aiofiles.open()` semantics. Without it, `open().write()` blocks the event loop during report export, potentially stalling the TUI or interview session running concurrently. | REPORT-03 |

**That's it.** Two new dependencies. Everything else is built on the existing stack.

### Why NOT More Dependencies

| Avoided | Why Not |
|---------|---------|
| LangChain / LangGraph | Massive dependency tree (50+ transitive deps). The ReACT loop is ~100 LOC of custom Python. LangChain's agent abstractions don't match AlphaSwarm's architecture (we have our own OllamaClient, governor, graph manager). Adding LangChain to call Ollama through their wrapper when we already have a wrapper is architectural debt. |
| LlamaIndex | Same problem as LangChain. We need 1 tool-dispatching loop, not a retrieval framework. Our "retrieval" is direct Cypher queries, not vector search. |
| markdown (Python-Markdown) | We're generating markdown, not parsing/rendering it to HTML. Jinja2 templates produce raw `.md` files. No HTML conversion needed. |
| python-markdown-generator | Overly abstracted for our use case. Jinja2 templates with markdown syntax are more readable and maintainable than programmatic markdown generation via method calls. |
| neo4j-graphrag | We don't need vector search or RAG pipelines. Our graph queries are handwritten Cypher optimized for our schema. |
| Datapane / reportlab | Web-based reporting frameworks. We're generating plain markdown files viewable in TUI or exported. No PDF/HTML dashboards needed. |
| APOC (Neo4j plugin) | Not needed for v2 features. All graph operations (rationale episodes, narrative edges, flip events) are expressible in pure Cypher with UNWIND batches. APOC adds Docker image complexity and security surface for no benefit. |

### Existing Dependencies -- Version Updates

| Library | Current Pin | Recommended Pin | Reason |
|---------|-------------|-----------------|--------|
| neo4j | >=5.28,<6.0 | >=5.28,<6.0 | **Keep as-is.** Neo4j driver 6.x (released 2026-01-12) requires Python >=3.10 and Neo4j server 2025.x+. Our docker-compose uses `neo4j:5.26-community`. Upgrading driver to 6.x would require upgrading the Neo4j server image simultaneously. This is scope creep for v2 -- the 5.x driver fully supports all v2 features (async sessions, UNWIND batches, transaction functions). Upgrade to 6.x in a future infrastructure phase. |
| textual | >=8.1.1 | >=8.1.1 | **Keep as-is.** Latest is 8.2.1 (2026-03-29). The `>=8.1.1` pin already allows 8.2.x via uv resolution. No API changes needed for v2 features -- Textual's Screen push/pop, Input widget, RichLog, and mode system are all available in 8.1.1+. |
| ollama | >=0.6.1 | >=0.6.1 | **Keep as-is.** Latest is still 0.6.1 (2025-11-13). The existing AsyncClient.chat() API handles everything v2 needs: multi-turn conversations (interview), streaming responses, and message history management. No native tool calling needed (see critical finding above). |

### Docker Compose -- No Changes

The existing `docker-compose.yml` with `neo4j:5.26-community` supports all v2 Neo4j features. No APOC plugin needed. No server version upgrade required.

## Feature-by-Feature Stack Mapping

### Phase 11: Agent Interviews (INT-01, INT-02, INT-03)

**New code, no new dependencies.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Interview context builder | Cypher queries via existing `neo4j` driver | Extends `GraphStateManager` with `read_agent_interview_context()` -- fetches persona, all 3 rounds of decisions, peer influences, rationale history for a single agent |
| Conversation loop | `ollama` AsyncClient.chat() | Multi-turn conversation using message list accumulation. System prompt = full persona + decision context. User messages = operator questions. Assistant messages = agent responses. Append each exchange to the list. |
| Context window management | Custom trimming logic | Worker model context window is ~4K tokens (qwen3.5:4b default). Interview context (persona + 3 rounds + rationale) could exceed this. Implement a sliding window: keep system prompt + last N exchanges, summarize earlier exchanges. |
| TUI interview mode | Textual `Screen` push/pop + `Input` widget + `RichLog` | Push an `InterviewScreen` on top of the main dashboard when user selects an agent. `Input` at bottom for questions, `RichLog` for scrollable conversation history. Pop screen to return to grid. |
| Model lifecycle | Existing `OllamaModelManager` | Worker model stays loaded post-simulation (INT-03). Set `keep_alive=-1` to prevent auto-unload, or simply don't call `unload_model()` after Round 3. |
| Streaming responses | `ollama` AsyncClient.chat(stream=True) | Stream interview responses token-by-token into the `RichLog` for real-time feel. Each chunk appends text. Final chunk triggers conversation history update. |

**Key design decision:** The interview uses the WORKER model (qwen3.5:4b/9b), not the orchestrator. The worker is already loaded post-simulation. Loading the 32b orchestrator for interviews would require unloading the worker and a ~30s cold load. Use the smaller model with rich context injection instead.

### Phase 12: Live Graph Memory (GRAPH-01, GRAPH-02, GRAPH-03)

**New code, no new dependencies.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Rationale episode nodes | Cypher via existing `neo4j` driver | New node type `:RationaleEpisode` with properties: `text`, `signal`, `confidence`, `sentiment`, `round`, `cycle_id`, `timestamp`. Connected to Agent via `[:EXPRESSED]` edge. Written during simulation, not after. |
| Signal flip events | Cypher via existing `neo4j` driver | New node type `:FlipEvent` with properties: `from_signal`, `to_signal`, `confidence_delta`, `round`, `cycle_id`. Connected to Agent via `[:FLIPPED]` edge. Computed in `_compute_shifts()` and persisted alongside ShiftMetrics. |
| Narrative edges | Cypher via existing `neo4j` driver | New relationship types: `[:REASONED_ABOUT]` (Agent -> Entity, with rationale text), `[:FLIPPED_BECAUSE]` (FlipEvent -> PeerDecision that triggered the flip). Built from citation analysis in existing `compute_influence_edges()`. |
| Real-time writes | Existing batch write pattern | Extend `write_decisions()` to also write RationaleEpisode nodes in the same UNWIND transaction. Zero additional Neo4j round-trips -- add the episode creation to the existing Cypher statement. |
| Schema extensions | `ensure_schema()` | Add indexes: `CREATE INDEX episode_cycle_round IF NOT EXISTS FOR (e:RationaleEpisode) ON (e.cycle_id, e.round)`, `CREATE INDEX flip_cycle IF NOT EXISTS FOR (f:FlipEvent) ON (f.cycle_id)`. |
| Graph exploration | Neo4j Browser (localhost:7474) | Already available. GRAPH-03 requires no code -- users open the browser and run Cypher queries against the enriched graph. Document useful exploration queries in a guide. |

**Memory impact:** Additional Neo4j writes add ~2-5ms per round (100 episodes in one UNWIND). Negligible compared to LLM inference time (~minutes).

### Phase 13: Post-Simulation Report (REPORT-01, REPORT-02, REPORT-03)

**New dependencies: Jinja2, aiofiles.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| ReACT loop | Custom Python (~100 LOC) | Prompt-based tool dispatching. System prompt defines available tools and ReACT format. Agent outputs `Thought: ... Action: tool_name: args`. Python parses via regex `r'^Action: (\w+): (.*)$'`, dispatches to registered functions, feeds `Observation: result` back. Loop until `Answer:` is emitted or max_turns exceeded. |
| Tool: consensus_summary | Cypher query function | `MATCH (d:Decision) WHERE d.cycle_id = $cid AND d.round = 3 RETURN d.signal, count(*) AS cnt, avg(d.confidence)` -- returns final signal distribution. |
| Tool: key_dissenters | Cypher query function | Find agents whose Round 3 signal disagrees with bracket majority. Returns agent_id, bracket, signal, rationale. |
| Tool: bracket_trends | Cypher query function | Per-bracket signal distribution across all 3 rounds. Shows convergence or divergence patterns. |
| Tool: flip_analysis | Cypher query function | `MATCH (f:FlipEvent) WHERE f.cycle_id = $cid RETURN f.from_signal, f.to_signal, count(*)` -- requires Phase 12 FlipEvent nodes. |
| Tool: influence_leaders | Cypher query function | Top-N agents by INFLUENCED_BY edge count. Returns agent_id, citation_count, bracket. |
| Report template | Jinja2 | Template file `templates/report.md.j2` with sections: Executive Summary, Consensus Distribution, Bracket Analysis, Key Dissenters, Signal Flip Analysis, Influence Network, Confidence Distribution. Each section uses Jinja2 loops and conditionals. |
| Report rendering | Jinja2 `Environment` | Load template, render with ReACT-gathered data dict. Output is a complete markdown string. |
| Report export | aiofiles | `async with aiofiles.open(f"reports/{cycle_id}.md", "w") as f: await f.write(rendered)`. Non-blocking file write. |
| TUI report viewer | Textual `RichLog` or `Static` | Push a `ReportScreen` that renders the markdown in the terminal using Rich's markdown renderer. |
| LLM for ReACT | Orchestrator model (qwen3.5:32b) | The ReACT agent needs reasoning capability to decide which tools to call and synthesize findings. Use the orchestrator model, not the worker. This means a model swap post-simulation: unload worker, load orchestrator, run ReACT loop, unload orchestrator. |

**Critical constraint:** The ReACT agent must use the ORCHESTRATOR model for quality reasoning. This requires a model swap after simulation completes (unload worker -> load orchestrator -> run report -> unload orchestrator). Budget ~30s for the cold load. The interview feature (Phase 11) should be offered BEFORE report generation, while the worker model is still loaded.

### Phase 14: Richer Agent Interactions (SOCIAL-01, SOCIAL-02)

**New code, no new dependencies.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Rationale posts | Extended `AgentDecision` model | Add `public_rationale: str` field -- a short, shareable version of the agent's reasoning (distinct from internal rationale). Generated by the LLM in the same inference call via an extended JSON schema. |
| Post storage | Cypher via existing `neo4j` driver | New node type `:Post` with properties: `text`, `agent_id`, `round`, `cycle_id`. Connected via `[:PUBLISHED]`. Stored in the same UNWIND batch as decisions. |
| Peer reading | Extended `read_peer_decisions()` | Include peer posts in the context injected for Rounds 2-3. Current peer context format: `[Bracket] SIGNAL (conf: X.XX) "rationale"`. Extended: add the peer's `public_rationale` as a quotable post. |
| Reactions | New relationship types | `[:AGREED_WITH]`, `[:DISAGREED_WITH]`, `[:CITED_POST]` edges between agents. Inferred from Round 2-3 LLM output -- if an agent's rationale references a specific peer's post, create the edge. |
| Engagement-based influence | Extended `compute_influence_edges()` | Current weight = citations / total_agents. Extended: weight += reaction_count * reaction_weight. Agents with highly-engaged posts gain more influence in subsequent rounds. |

**Prompt engineering, not code engineering:** The main work is crafting prompts that make agents produce public rationale posts AND react to peers' posts. The JSON output schema extends from `{signal, confidence, sentiment, rationale, cited_agents}` to `{signal, confidence, sentiment, rationale, public_rationale, cited_agents, reactions: [{agent_id, reaction_type}]}`. Parsing extends the existing `parse_agent_decision()` 3-tier fallback.

### Phase 15: Dynamic Persona Generation (PERSONA-01, PERSONA-02)

**New code, no new dependencies.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Entity-aware persona generation | Orchestrator LLM (qwen3.5:32b) | Extend `inject_seed()` to also generate dynamic personas. After entity extraction, a second orchestrator call generates 5-15 situation-specific personas based on extracted entities (e.g., oil rumor -> energy trader, OPEC analyst, pipeline engineer). |
| Dynamic persona schema | Pydantic model | New `DynamicPersona` model extending `AgentPersona` with `origin: Literal["static", "dynamic"]` and `entity_context: str` fields. Dynamic personas supplement (not replace) the standard 100 agents. |
| Persona count management | Configuration | Total agent count becomes configurable: 100 static + N dynamic (where N = 5-15 based on seed complexity). ResourceGovernor budget must account for the additional agents. Add `max_dynamic_agents: int = 15` to `AppSettings`. |
| Prompt template | Existing `system_prompt_template` pattern | Dynamic personas use the same prompt structure as static personas but with entity-specific context injected: `"You are a {role} with deep expertise in {entity}. Given recent developments in {sector}..."`. |

**Memory constraint:** Each additional agent adds one more inference call per round. 15 extra agents across 3 rounds = 45 additional inferences. With the current governor, this adds ~2-3 minutes to simulation time. Acceptable.

## Installation

```bash
# New v2 dependencies (add to existing pyproject.toml)
uv add jinja2 aiofiles

# Dev dependencies (no changes)
# Existing: pytest, pytest-asyncio, pytest-cov, ruff, mypy

# No Docker changes needed
# No Ollama model changes needed
# No Neo4j server upgrade needed
```

Updated `pyproject.toml` dependencies section:

```toml
dependencies = [
    "pydantic>=2.12.5",
    "pydantic-settings>=2.13.1",
    "structlog>=25.5.0",
    "psutil>=7.2.2",
    "ollama>=0.6.1",
    "backoff>=2.2.1",
    "neo4j>=5.28,<6.0",
    "textual>=8.1.1",
    # v2 additions
    "jinja2>=3.1.6",
    "aiofiles>=24.1.0",
]
```

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Ollama native tool calling (`tools=` param) | Broken with qwen3.5 models (wrong XML/JSON format mismatch, unclosed think tags). GitHub issues #14493, #14745 confirm as of 2026-03-31. | Prompt-based ReACT with regex parsing (~100 LOC) |
| LangChain / LangGraph | 50+ transitive deps, wrong abstraction (we have our own inference pipeline). Would require wrapping our OllamaClient in their LLM interface, adding indirection for no benefit. | Custom ReACT loop that directly uses our existing OllamaClient |
| LlamaIndex | Vector RAG framework -- we do graph queries, not embedding search. Massive dep tree. | Direct Cypher queries via neo4j driver |
| APOC Neo4j plugin | Not needed. All v2 graph operations are pure Cypher. APOC adds Docker complexity, version pinning headaches, and security surface. | Pure Cypher with UNWIND batches |
| neo4j driver 6.x | Requires Neo4j server upgrade (5.26 -> 2025.x), potential breaking changes. Zero features in 6.x that v2 needs. | Keep neo4j >=5.28,<6.0 |
| Separate Markdown rendering lib | We generate markdown (text), not render it to HTML. Jinja2 produces .md files directly. | Jinja2 templates with markdown syntax |
| WebSocket for TUI-interview comm | Single-process app. Interview runs in the same asyncio loop as TUI. No IPC needed. | Direct async function calls within Textual Worker |

## Architecture Patterns for v2

### ReACT Report Agent (No Framework)

```python
# Minimal ReACT loop -- no LangChain needed
import re

ACTION_RE = re.compile(r"^Action: (\w+): (.*)$", re.MULTILINE)

TOOLS = {
    "consensus_summary": query_consensus_summary,  # Cypher function
    "key_dissenters": query_key_dissenters,
    "bracket_trends": query_bracket_trends,
    "flip_analysis": query_flip_analysis,
    "influence_leaders": query_influence_leaders,
}

async def run_react_report(client: OllamaClient, model: str, cycle_id: str, graph: GraphStateManager) -> str:
    messages = [{"role": "system", "content": REACT_SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": f"Generate a market analysis report for cycle {cycle_id}."})

    for turn in range(MAX_TURNS):
        response = await client.chat(model=model, messages=messages, think=True)
        content = response.message.content or ""
        messages.append({"role": "assistant", "content": content})

        match = ACTION_RE.search(content)
        if match:
            tool_name, tool_input = match.groups()
            if tool_name in TOOLS:
                observation = await TOOLS[tool_name](graph, cycle_id, tool_input)
                messages.append({"role": "user", "content": f"Observation: {observation}"})
            else:
                messages.append({"role": "user", "content": f"Observation: Unknown tool '{tool_name}'."})
        else:
            # No action found -- agent is done
            return content

    return content  # max turns exceeded
```

### Interview Conversation Loop

```python
# Multi-turn interview using existing OllamaClient
async def interview_agent(client: OllamaClient, model: str, context: InterviewContext) -> AsyncGenerator[str, str]:
    messages = [
        {"role": "system", "content": context.build_system_prompt()},
    ]
    while True:
        question = yield  # Receive question from TUI
        messages.append({"role": "user", "content": question})

        # Stream response
        full_response = ""
        async for chunk in await client.chat(model=model, messages=messages, stream=True):
            token = chunk.message.content or ""
            full_response += token
            yield token  # Send token to TUI for real-time display

        messages.append({"role": "assistant", "content": full_response})

        # Trim history if approaching context limit
        if estimate_tokens(messages) > MAX_CONTEXT * 0.8:
            messages = trim_conversation(messages, keep_system=True, keep_recent=6)
```

### Textual Screen Modes for Post-Simulation

```python
# Textual mode switching for interview vs report vs grid
class AlphaSwarmApp(App):
    MODES = {
        "simulation": SimulationScreen,   # Main 10x10 grid
        "interview": InterviewScreen,      # Chat interface
        "report": ReportScreen,            # Rendered markdown
    }

    # Post-simulation: push interview screen
    def action_interview(self, agent_id: str) -> None:
        self.push_screen(InterviewScreen(agent_id=agent_id))

    # After interview: push report screen
    def action_generate_report(self) -> None:
        self.push_screen(ReportScreen(cycle_id=self.cycle_id))
```

## Version Compatibility Matrix

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| jinja2 >=3.1.6 | Python >=3.7, pydantic >=2.x | No conflicts. Jinja2 has zero overlapping deps with existing stack. |
| aiofiles >=24.1.0 | Python >=3.8, asyncio | Thread pool executor under the hood. Compatible with Textual's event loop. |
| neo4j >=5.28,<6.0 | Neo4j server 5.x (our docker-compose uses 5.26) | Pinned correctly. Do NOT upgrade to 6.x without server upgrade. |
| ollama >=0.6.1 | Ollama server 0.5+ | Streaming, tool schemas, async client all stable at 0.6.1. |
| textual >=8.1.1 | Python >=3.9, rich >=14.x | Screen modes, Input, RichLog all available. 8.2.1 (latest) is compatible. |

## Model Strategy for v2 Features

| Feature | Model | Why | Memory Impact |
|---------|-------|-----|---------------|
| Agent Interviews | Worker (qwen3.5:4b or 9b) | Already loaded post-simulation. No cold load needed. Fast responses. | None (model already loaded) |
| Live Graph Memory | N/A (pure Cypher) | No LLM needed. Graph writes happen during simulation alongside existing decision writes. | ~5ms/round additional Neo4j I/O |
| ReACT Report Agent | Orchestrator (qwen3.5:32b) | Needs reasoning capability to decide tool usage and synthesize findings. Worker model too small for multi-step reasoning. | Requires model swap: unload worker (~3.4GB freed), load orchestrator (~18GB). ~30s cold load. |
| Richer Interactions | Worker (qwen3.5:4b or 9b) | Extended inference during existing rounds. Same model, slightly larger JSON output schema. | ~10% more tokens per agent (longer output with public_rationale + reactions). Negligible. |
| Dynamic Personas | Orchestrator (qwen3.5:32b) | Persona generation is a seed injection extension. Orchestrator already loaded during seed phase. | None (runs during existing orchestrator phase). |

**Post-simulation model lifecycle:**
1. Simulation completes -- worker model still loaded
2. Offer **Agent Interviews** (uses worker model, no swap needed)
3. User finishes interviews, requests report
4. Unload worker, load orchestrator (~30s)
5. Run **ReACT Report Agent** (uses orchestrator)
6. Unload orchestrator
7. Export report to file

## Sources

- [Ollama Python PyPI (v0.6.1)](https://pypi.org/project/ollama/) -- verified latest version, streaming/async API
- [Ollama tool calling docs](https://docs.ollama.com/capabilities/tool-calling) -- native tool calling API reference
- [Qwen 3.5 tool calling bug #14493](https://github.com/ollama/ollama/issues/14493) -- confirmed broken, partial fix insufficient
- [Qwen 3.5 tool calling bug #14745](https://github.com/ollama/ollama/issues/14745) -- 9b variant prints tool calls as text
- [Simon Willison ReACT pattern](https://til.simonwillison.net/llms/python-react-pattern) -- minimal Python ReACT implementation (~100 LOC)
- [Jinja2 PyPI (v3.1.6)](https://pypi.org/project/Jinja2/) -- Python >=3.7, latest stable
- [aiofiles PyPI](https://pypi.org/project/aiofiles/) -- async file I/O for asyncio
- [Neo4j Python driver PyPI (v6.1.0)](https://pypi.org/project/neo4j/) -- confirmed 5.x compatibility, 6.x available but not needed
- [Neo4j Python async driver docs](https://neo4j.com/docs/python-manual/current/concurrency/) -- concurrent transaction patterns
- [Textual PyPI (v8.2.1)](https://pypi.org/project/textual/) -- latest version, Screen/mode system docs
- [Textual Screens guide](https://textual.textualize.io/guide/screens/) -- push/pop, mode switching
- [Textual RichLog widget](https://textual.textualize.io/widgets/rich_log/) -- real-time scrollable content
- [Textual chat TUI example](https://chaoticengineer.hashnode.dev/textual-and-chatgpt) -- Input + VerticalScroll chat pattern
- [Ollama conversation history](https://deepwiki.com/ollama/ollama-python/4.7-conversation-history) -- message list accumulation pattern
- [Ollama context length docs](https://docs.ollama.com/context-length) -- default 2K context, configurable via Modelfile

---
*Stack research for: AlphaSwarm v2.0 Engine Depth*
*Researched: 2026-03-31*
*Builds on: v1 stack research from 2026-03-24*
