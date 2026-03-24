# Domain Pitfalls

**Domain:** Multi-agent LLM financial simulation engine (local inference, 100 agents, M1 Max 64GB)
**Researched:** 2026-03-24

---

## Critical Pitfalls

Mistakes that cause rewrites, project-killing performance failures, or architectural dead ends.

---

### Pitfall 1: Unified Memory Budget Arithmetic -- The 70B + 7B + 16 Parallel Slots Math Does Not Close

**What goes wrong:** The project spec calls for `llama4:70b` (orchestrator) and `qwen3.5:7b` (100 worker agents) loaded simultaneously (`OLLAMA_MAX_LOADED_MODELS=2`) with `OLLAMA_NUM_PARALLEL=16` on M1 Max 64GB. The memory math is fatally tight:

| Component | Memory |
|-----------|--------|
| Llama 4 70B Q4_K_M base weights | ~38-42 GB |
| Qwen 3.5 7B Q4_K_M base weights | ~6-8 GB |
| KV cache for 16 parallel slots (7B model, 2K context each) | ~2-4 GB |
| KV cache for 70B orchestrator (1 slot, 4K context) | ~2-3 GB |
| **Subtotal: model inference** | **~48-57 GB** |
| macOS kernel + system services | ~3-4 GB |
| Neo4j JVM heap (default) | ~1-2 GB |
| Python runtime + asyncio + Textual | ~1-2 GB |
| **Total** | **~53-65 GB** |

Apple's Metal driver caps GPU memory at 75% of unified RAM by default -- that is **~48 GB** on a 64GB system. Even with the `sysctl iogpu.wired_limit_mb` override pushing to ~90% (~57 GB), having both models loaded with 16 parallel slots will cause memory pressure events, swap thrashing, and macOS may terminate the Ollama process entirely.

**Why it happens:** Developers estimate model memory from base weights alone, forgetting that `OLLAMA_NUM_PARALLEL` multiplies context (and therefore KV cache) allocation. Required RAM scales as `OLLAMA_NUM_PARALLEL * OLLAMA_CONTEXT_LENGTH * per-slot-overhead`. 16 parallel slots on a 7B model at 2K context can add 2-4 GB on top of the 8 GB base weight.

**Consequences:**
- macOS kills the Ollama process under memory pressure with no warning (jetsam)
- Inference speed degrades catastrophically as the system swaps to disk (NVMe swap on Apple Silicon is fast but still 10-50x slower than unified memory)
- Model unloading/reloading mid-simulation destroys the 3-round cascade timing -- a cold reload of the 70B model takes 30-45 seconds

**Prevention:**
1. Apply the Metal GPU memory override: `sudo sysctl iogpu.wired_limit_mb=57344` (90% of 64GB)
2. Do NOT keep both models loaded simultaneously. Use a sequential architecture: load 70B for seed parsing, unload, then load 7B for the 100-agent cascade. The 70B model is only needed at the start (seed injection) and end (consensus aggregation) -- not during the 3-round agent processing
3. Reduce `OLLAMA_NUM_PARALLEL` to 8 (not 16) as the baseline. The ResourceGovernor should dynamically reduce further under pressure
4. Use KV cache quantization: set `OLLAMA_KV_CACHE_TYPE=q8_0` to reduce KV cache memory by ~50% vs the default f16
5. Enforce strict context length: set agent prompts to use the minimum viable context (1024-2048 tokens, not the model default of 4096+)
6. Implement psutil-based monitoring that checks `psutil.virtual_memory().percent` and throttles the semaphore BEFORE hitting 90% -- aim for 80% as the throttle trigger

**Detection:**
- Monitor `psutil.virtual_memory().percent` continuously; alarm at 80%, hard-stop new inference at 90%
- Watch for Ollama 503 errors (queue saturation) or sudden response time spikes (model reload)
- Log Ollama's actual loaded model state via `GET /api/ps` before each batch

**Confidence:** HIGH -- memory numbers verified against multiple sources including Ollama documentation, llama.cpp benchmarks, and Apple Silicon memory architecture documentation.

**Phase:** Must be addressed in Phase 1 (core engine). This is the single most likely project-killer.

---

### Pitfall 2: Ollama Context Size Mismatch Triggers Silent Model Reloads

**What goes wrong:** When different requests to the same model specify different context sizes (via `num_ctx` parameter), Ollama unloads and reloads the model with the new context configuration. In AlphaSwarm, if the orchestrator sends a prompt with `num_ctx=4096` and a worker agent sends `num_ctx=2048`, Ollama silently unloads and reloads the model. With a 7B model, this adds 5-10 seconds per reload. For a 70B model, 30-45 seconds.

**Why it happens:** Ollama's KV cache is pre-allocated at model load time based on context size. A request with a different `num_ctx` forces a full teardown and rebuild of the KV cache, which means unloading the model entirely and reloading it. This is not documented prominently and catches nearly every multi-component project that uses Ollama.

**Consequences:**
- A 100-agent simulation that should take minutes takes hours due to silent reloads
- The 3-round cascade breaks entirely because reload latency exceeds reasonable timeout windows
- Inconsistent behavior -- sometimes fast (context matches), sometimes inexplicably slow (context mismatch)

**Prevention:**
1. Standardize `num_ctx` across ALL requests to the same model. Pick one value (e.g., 2048 for worker agents) and never deviate
2. Create Ollama Modelfiles that bake in the context size: `PARAMETER num_ctx 2048` so it cannot be overridden
3. Pin the orchestrator model's context separately: create a `llama4-orch:70b` Modelfile with `PARAMETER num_ctx 4096`
4. Never pass `num_ctx` in API requests -- let the Modelfile handle it

**Detection:**
- Log timestamps of every Ollama API call and flag any response that takes >5x the median latency
- Use `GET /api/ps` to check model load state before and after each batch
- If you see the same model appearing in `ollama list` output with different parameter hashes, you have this bug

**Confidence:** HIGH -- this behavior is documented in Ollama issues and the official FAQ.

**Phase:** Phase 1 (core engine). Must be addressed when designing the Ollama client wrapper.

---

### Pitfall 3: Ruflo v3.5 Is a Claude Code Orchestrator, Not a Python Simulation Framework

**What goes wrong:** The project spec designates "Ruflo v3.5 (Hierarchical Swarm logic)" as the orchestration layer. Ruflo is a Node.js/TypeScript-based Claude Code extension for orchestrating AI coding agents (60+ specialized agents for software development tasks). It is NOT a Python library, does not embed into Python applications, and has no API for controlling Ollama-based financial simulation agents. It solves an entirely different problem.

**Why it happens:** Name confusion or surface-level feature overlap. Ruflo uses terms like "swarm," "hierarchical," and "consensus" which sound applicable to a multi-agent financial simulation, but these refer to coordinating Claude Code instances for software engineering tasks, not general-purpose agent simulation.

**Consequences:**
- Attempting to integrate Ruflo wastes weeks on a fundamentally incompatible architecture
- The project needs a Python-native orchestration approach, and discovering this late forces a rewrite of the orchestration layer
- The hierarchical swarm logic (queen agents, bracket coordination, influence topology) must be built from scratch in Python

**Prevention:**
1. Drop Ruflo from the stack entirely
2. Build the orchestration layer in pure Python using `asyncio` primitives: `asyncio.Semaphore` for concurrency control, `asyncio.Queue` for the task pipeline, and a custom `SwarmOrchestrator` class that manages the 3-round cascade
3. The hierarchical structure (10 bracket archetypes, influence topology) is domain-specific to this simulation and is better served by a custom implementation than any generic framework
4. If a framework is desired, evaluate Langroid (Python-native, async, supports Ollama) or build on the Ollama Python client's `AsyncClient` directly

**Detection:** Try `pip install ruflo` -- it does not exist. The npm package is `claude-flow` (Ruflo's distribution name).

**Confidence:** HIGH -- verified directly from the Ruflo GitHub repository and npm package. It is a Node.js application requiring `npx` installation.

**Phase:** Phase 0 (project setup / architecture decision). This must be resolved before any code is written.

---

### Pitfall 4: Neo4j AsyncSession Is Not Concurrency-Safe -- One Session Per Coroutine

**What goes wrong:** Developers share a single `AsyncSession` across multiple `asyncio.Task` instances (e.g., 100 agent coroutines all reading/writing through one session). The Neo4j Python driver documentation explicitly states: "Sessions are not safe to be used in concurrent contexts (multiple threads/coroutines). A session should generally be short-lived and must not span multiple threads/asynchronous Tasks."

Compounding this: `asyncio.wait_for()` and `asyncio.shield()` wrap work in new `asyncio.Task` objects, which introduces concurrency even when you think you are in a single coroutine.

**Why it happens:** Sessions look lightweight and developers assume they are like connection-pooled HTTP clients. In reality, each session maintains transaction state and is not safe for concurrent use.

**Consequences:**
- Corrupted reads: agents see stale or interleaved data from other agents' transactions
- `asyncio error: read() called while another coroutine is already waiting for incoming data` -- this is a documented Neo4j Python driver issue (#945)
- Deadlocks under concurrent write pressure, especially when creating INFLUENCED_BY edges where multiple agents reference the same peer

**Prevention:**
1. Use `driver.execute_query()` for simple read/write operations -- it handles session lifecycle internally and is the recommended approach for most use cases
2. If you must use sessions: create a new `AsyncSession` per coroutine, use it in an `async with` block, and let it close immediately after the operation
3. For the 100-agent read phase (Round 2: Peer Influence), batch reads using `UNWIND` with a list of agent IDs rather than 100 individual queries:
   ```cypher
   UNWIND $agent_ids AS aid
   MATCH (a:Agent {id: aid})-[r:INFLUENCED_BY]->(peer:Agent)
   WHERE r.cycle_id = $cycle_id
   RETURN a.id, collect(peer.sentiment) AS peer_sentiments
   ```
4. Install `neo4j-rust-ext` for 3-10x driver speedup: `pip install neo4j-rust-ext`
5. Size the connection pool to match your concurrency: if you run 16 parallel agent batches, set `max_connection_pool_size=32` (2x headroom)

**Detection:**
- The `read() called while another coroutine is already waiting` error is the smoking gun
- Intermittent data inconsistencies that only appear under load (not in single-agent tests)
- Neo4j transaction timeouts that only happen when OLLAMA_NUM_PARALLEL > 1

**Confidence:** HIGH -- documented in Neo4j Python driver manual and issue tracker.

**Phase:** Phase 1 (core engine). Must be built correctly from the start -- retrofitting session-per-coroutine into a shared-session design is a significant rewrite.

---

### Pitfall 5: asyncio Task Reference Garbage Collection ("The Heisenbug")

**What goes wrong:** When you call `asyncio.create_task()` without storing a reference to the returned Task object, Python's garbage collector may silently destroy the task. The coroutine stops executing with no error, no warning, and no traceback. For AlphaSwarm's 100-agent simulation, this means agents silently disappear from the cascade -- you get 87 results instead of 100 and have no idea why.

**Why it happens:** Unlike threads (where non-daemon threads persist for the application lifetime), asyncio Tasks are normal Python objects subject to garbage collection. If the only reference is the event loop's weak reference, the GC can collect the task at any time. This is a well-documented Python behavior but remains one of the most common asyncio bugs.

**Consequences:**
- Agents silently drop out of the simulation with zero error output
- Results are non-deterministic -- depends on when GC runs (hence "Heisenbug" -- observation changes behavior)
- Extremely difficult to debug because adding logging or breakpoints changes GC timing

**Prevention:**
1. Use `asyncio.TaskGroup` (Python 3.11+) for all agent batch processing. TaskGroup maintains internal references and prevents GC collection:
   ```python
   async with asyncio.TaskGroup() as tg:
       tasks = [tg.create_task(process_agent(agent)) for agent in batch]
   # All tasks guaranteed to complete or raise
   ```
2. If using `create_task` directly, always store references in a set:
   ```python
   _background_tasks = set()
   task = asyncio.create_task(process_agent(agent))
   _background_tasks.add(task)
   task.add_done_callback(_background_tasks.discard)
   ```
3. Never use bare `asyncio.create_task(coro())` as a fire-and-forget pattern

**Detection:**
- Count results: if you dispatched 100 agents but got 94 responses, you likely have this bug
- Enable `asyncio` debug mode: `PYTHONASYNCIODEBUG=1` -- it logs warnings about destroyed tasks
- Add a task completion counter and assert it matches the dispatch count

**Confidence:** HIGH -- documented by the Textual framework team and in Python asyncio documentation.

**Phase:** Phase 1 (core engine). Must be a design constraint from the first coroutine.

---

### Pitfall 6: Neo4j Write Lock Contention and Deadlocks During Influence Edge Creation

**What goes wrong:** During Round 2 (Peer Influence) and Round 3 (Final Consensus Lock), multiple agents concurrently create or update INFLUENCED_BY edges and sentiment properties on the same nodes. Neo4j uses node-level write locks. If Agent A writes to Node X while Agent B writes to Node Y, but both also try to create edges to a popular node (e.g., a Whale), circular lock dependencies cause deadlocks. Neo4j detects these and throws `DeadlockDetectedException`, aborting one transaction.

**Why it happens:** In AlphaSwarm's influence topology, high-influence agents (Whales with 5 agents, Quants with 10) are likely to be referenced by many other agents simultaneously. This creates "hot nodes" -- nodes that many concurrent transactions try to lock. Neo4j's relationship chain locking means that creating a relationship to a node also locks the node's relationship chain.

**Consequences:**
- `DeadlockDetectedException` aborts transactions, requiring retry logic
- Without retries, agents lose their Round 2/3 updates and the consensus cascade is corrupted
- Under heavy contention, retries can cascade into a retry storm where every retry also deadlocks

**Prevention:**
1. Batch all edge writes for a given round into a single transaction using `UNWIND`:
   ```cypher
   UNWIND $edges AS edge
   MATCH (a:Agent {id: edge.source}), (b:Agent {id: edge.target})
   CREATE (a)-[:INFLUENCED_BY {cycle_id: $cycle_id, round: $round, weight: edge.weight}]->(b)
   ```
   This ensures all edges in a batch are written in a deterministic order, preventing cross-transaction deadlocks
2. Process writes sequentially per round (all agents complete inference, then ONE batch write), not per-agent (each agent writes individually after inference)
3. If concurrent writes are necessary, ensure a consistent global ordering: always acquire locks in ascending agent ID order
4. Use `ON ERROR RETRY` in Cypher `CALL { ... } IN CONCURRENT TRANSACTIONS` for deadlock recovery
5. Separate read and write phases: all agents read in parallel (safe), then all writes are batched

**Detection:**
- `DeadlockDetectedException` in Neo4j logs
- Transaction retry counts exceeding 3 per batch
- Round completion time variance >10x between runs

**Confidence:** HIGH -- deadlock behavior is documented in Neo4j Operations Manual and community reports of concurrent edge creation failures.

**Phase:** Phase 1 (core engine). The data access pattern must be designed for batch writes from day one.

---

## Moderate Pitfalls

Mistakes that cause significant performance degradation or require non-trivial rework.

---

### Pitfall 7: Textual TUI Freezes When Agent Coroutines Push Per-Update UI Changes

**What goes wrong:** Textual runs on Python's asyncio event loop. If 100 agent coroutines each call `widget.update()` or modify reactive variables after every inference completion, the UI thread processes 100+ render cycles in rapid succession, blocking the event loop and freezing the TUI. Even though Textual's task overhead is low (~260K tasks/second), the CSS reflow and DOM diffing per update is not.

The project spec wisely calls for "Snapshot-based TUI rendering (200ms tick)" but the temptation to bypass this during development is strong, and it only takes one `self.app.query_one('#grid').update(...)` call from inside an agent coroutine to break the pattern.

**Why it happens:** Textual's reactive system triggers watchers and re-renders synchronously on the event loop. One agent completing does not warrant a render -- but the natural developer instinct is to update the UI immediately.

**Prevention:**
1. Enforce the snapshot architecture: agent coroutines write to a shared `dict` (or dataclass), and a single `set_interval(0.2)` timer reads the snapshot and updates the TUI:
   ```python
   class Dashboard(App):
       def on_mount(self):
           self.set_interval(0.2, self.refresh_grid)

       def refresh_grid(self):
           snapshot = self.state_manager.get_snapshot()
           self.grid.update_from_snapshot(snapshot)
   ```
2. Never import or reference Textual widgets from agent coroutines. The agent layer should have zero knowledge of the UI layer
3. Use `App.call_from_thread()` only if you must bridge threaded workers to the UI -- but prefer the snapshot pattern entirely
4. Set reactive variables on widgets only from the timer callback, never from agent code

**Detection:**
- TUI becomes unresponsive during simulation (can't scroll, can't press keys)
- Event loop lag visible in `asyncio` debug mode
- Profiling shows time spent in Textual CSS layout during agent processing

**Confidence:** HIGH -- documented in Textual's official workers guide and blog posts.

**Phase:** Phase 1 (TUI implementation). The snapshot architecture must be the only data flow path from agents to UI.

---

### Pitfall 8: asyncio.Semaphore Permit Leak Under Exception Causes Progressive Slowdown

**What goes wrong:** The ResourceGovernor uses `asyncio.Semaphore` to limit concurrent Ollama requests. If an Ollama call raises an exception (timeout, 503, connection refused) after the semaphore is acquired but the release is not in a `finally` block or `async with` context, the permit is permanently lost. After enough failures, the semaphore counter reaches 0 and all future coroutines block forever -- a silent deadlock.

Additionally, over-releasing (calling `release()` more times than `acquire()`) inflates the semaphore counter above its initial value, defeating the concurrency limit entirely. This can happen if retry logic releases on both success and failure paths.

**Why it happens:** Manual `acquire()`/`release()` without structured cleanup. Ollama failures are common under memory pressure (the exact conditions where you need the semaphore most).

**Consequences:**
- Progressive slowdown as permits leak (hard to distinguish from legitimate load)
- Eventually complete deadlock: all agents block on semaphore acquire forever
- Or the opposite: counter inflation defeats rate limiting and triggers OOM

**Prevention:**
1. Always use `async with semaphore:` -- never manual acquire/release:
   ```python
   async with self.inference_semaphore:
       result = await self.ollama_client.generate(...)
   ```
2. The ResourceGovernor's dynamic adjustment should create a NEW semaphore with the adjusted value, not call release/acquire to adjust:
   ```python
   # Wrong: self.semaphore.release() to increase capacity
   # Right: self.semaphore = asyncio.Semaphore(new_limit)
   ```
   Note: replacing the semaphore object while coroutines are waiting on it requires careful handling -- use a wrapper that delegates to the current semaphore
3. Add semaphore health monitoring: log `semaphore._value` periodically and alert if it drifts from expected

**Detection:**
- Throughput decreases over time even though system load is stable
- `semaphore._value` drops below 0 (leaked) or rises above initial value (over-released)
- Agent batches that never complete (hung on semaphore acquire)

**Confidence:** HIGH -- well-documented asyncio pattern. The Ollama-specific failure modes make this especially likely in AlphaSwarm.

**Phase:** Phase 1 (ResourceGovernor implementation).

---

### Pitfall 9: psutil Reports Misleading Memory Data on macOS Apple Silicon

**What goes wrong:** The project uses `psutil.virtual_memory().percent` to monitor memory pressure and throttle the inference semaphore. On macOS with Apple Silicon, psutil has known issues: `psutil.cpu_freq()` may not work, and virtual memory statistics can be inaccurate because macOS uses a compressed memory system where `available` memory is not a straightforward concept. More critically, psutil cannot distinguish between memory used by the GPU (Metal) and memory used by CPU processes -- on unified memory architecture, they are the same pool but managed differently.

**Why it happens:** psutil was designed for traditional architectures with separate CPU/GPU memory. Apple Silicon's unified memory architecture breaks assumptions about what "available" memory means. macOS may show 95% memory usage but the system is perfectly healthy because compressed memory is working efficiently. Conversely, macOS may show 80% usage but Ollama is about to be killed because Metal has hit its allocation ceiling.

**Consequences:**
- ResourceGovernor throttles prematurely (false high pressure) or too late (false low pressure)
- The 90% threshold from the spec may trigger constantly under normal operation, killing throughput
- Or the threshold may never trigger before macOS jetsam kills Ollama

**Prevention:**
1. Use macOS-specific memory pressure APIs instead of (or in addition to) psutil:
   ```python
   import subprocess
   result = subprocess.run(['memory_pressure'], capture_output=True, text=True)
   # Parse "System-wide memory free percentage: XX%"
   ```
2. Monitor Ollama's own memory reporting via `GET /api/ps` which shows per-model memory allocation
3. Use `psutil.Process(ollama_pid).memory_info().rss` to track Ollama's specific memory usage rather than system-wide
4. Set the throttle threshold based on empirical testing, not an arbitrary 90%. Profile the actual system with both models loaded and calibrate
5. Consider monitoring swap usage (`psutil.swap_memory().used`) as a more reliable pressure signal -- any swap activity on Apple Silicon indicates real pressure

**Detection:**
- ResourceGovernor throttles during periods of actually-fine system performance
- Ollama gets killed by jetsam despite ResourceGovernor showing "under threshold"
- Swap usage climbing while psutil reports plenty of free memory

**Confidence:** MEDIUM -- psutil limitations on Apple Silicon are documented in GitHub issues, but the specific impact on AlphaSwarm's use case requires empirical validation.

**Phase:** Phase 1 (ResourceGovernor). Requires empirical calibration during early development.

---

### Pitfall 10: Miro API Credit-Based Rate Limiting Is More Restrictive Than It Appears

**What goes wrong:** The project spec mandates a "2-second buffer" between Miro API calls. But Miro's rate limiting is credit-based (100,000 credits/minute), not time-based. Different operations cost different credits:

| Tier | Credit Cost | Max Requests/Min |
|------|-------------|------------------|
| Level 1 (reads) | 50 credits | 2,000 |
| Level 2 (simple writes) | 100 credits | 1,000 |
| Level 3 (complex writes) | 500 credits | 200 |
| Level 4 (bulk operations) | 2,000 credits | 50 |

Creating 100 agent nodes + edges in a Miro board uses Level 3-4 operations. At 2,000 credits per bulk create, you get only 50 bulk operations per minute. If visualizing a full 100-agent topology with edges, a single cascade round could require 5-10 bulk operations (nodes + edges + position updates + color updates), which is fine, but rapid re-rendering across 3 rounds could hit the ceiling.

**Why it happens:** Developers implement time-based rate limiting (fixed 2-second delay) when the actual constraint is credit-based. A 2-second delay between Level 1 reads is wasteful (you could do 33/second). A 2-second delay between Level 4 bulk writes is insufficient if you send many in a burst.

**Consequences:**
- 429 errors despite the 2-second buffer, because credit costs exceed expectations
- Over-conservative throttling on reads that could be faster
- Hitting the per-minute credit ceiling during rapid visualization updates

**Prevention:**
1. Implement credit-aware rate limiting, not time-based:
   ```python
   class MiroBatcher:
       credits_remaining: int = 100_000
       reset_at: float  # from X-RateLimit-Reset header

       async def execute(self, operation, tier_cost):
           if self.credits_remaining < tier_cost:
               await asyncio.sleep(self.seconds_until_reset())
           # ... execute and update from response headers
   ```
2. Parse `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers from every Miro API response
3. Batch node and edge creation into single bulk API calls (the project spec already notes this)
4. For 429 responses, parse the `Retry-After` header and add jitter (the spec's exponential backoff strategy)
5. Since Miro is deferred to Phase 2, stub the batcher interface now but implement credit tracking from the start

**Detection:**
- 429 responses despite time-based buffering
- `X-RateLimit-Remaining` approaching 0 mid-minute

**Confidence:** HIGH -- rate limit tiers verified from Miro API v2 official documentation.

**Phase:** Phase 2 (Miro integration). Stub the batcher interface in Phase 1 but the credit-based logic is Phase 2.

---

### Pitfall 11: Multi-Agent Consensus Cascade Produces Homogeneous Output ("Echo Chamber Effect")

**What goes wrong:** In the 3-round cascade, agents read peers' outputs in Round 2 and adjust their sentiment. If the prompt engineering does not enforce diversity, agents rapidly converge to the same opinion by Round 3. A simulation of 100 agents that all agree on "Buy" is useless -- it produces a consensus graph with zero information content.

Research on multi-agent LLM systems shows that "cascading failures" are a primary failure mode: "a single misinterpreted message or misrouted output early in the workflow can cascade through subsequent steps." In a financial simulation, if the first batch of agents (e.g., 16 Quants) all output "Buy" because they share the same archetype prompt, the second batch reads 16 "Buy" signals and follows suit.

**Why it happens:**
- Archetype prompts are not sufficiently differentiated (Degens and Quants both react positively to the same signal)
- Temperature settings are too low (deterministic responses from same prompt)
- Round 2 peer reading does not weight influence correctly (agents treat all peers equally)
- No "contrarian bias" built into archetypes like Doom-Posters

**Consequences:**
- The simulation produces meaningless uniform consensus
- The dynamic influence topology has no diversity to visualize
- The product's core value proposition (believable, diverse market reactions) is destroyed

**Prevention:**
1. Design archetype system prompts with explicit behavioral constraints:
   - Doom-Posters: "You are constitutionally skeptical. You require 3x the evidence to go bullish vs bearish"
   - Sovereigns: "You react to second-order effects only. If everyone else is bullish, you worry about crowded trades"
2. Use different temperature settings per archetype: Degens at 1.2, Suits at 0.3, Quants at 0.7
3. In Round 2, weight peer influence by bracket relationship, not uniformly. Doom-Posters should be minimally influenced by Degens
4. Add a diversity metric: measure sentiment distribution after each round. If standard deviation drops below a threshold, inject "contrarian noise" into remaining agent prompts
5. Test with known inputs that should produce diverse outputs and regression-test against homogeneity

**Detection:**
- Sentiment standard deviation across 100 agents drops below 0.2 (on a -1 to 1 scale) by Round 2
- More than 80% of agents reach the same Buy/Sell/Hold decision
- Influence topology graph has one giant cluster and no opposing clusters

**Confidence:** MEDIUM -- based on multi-agent LLM research (arxiv:2503.13657) and general LLM behavior patterns, but specific to AlphaSwarm's domain. Requires empirical tuning.

**Phase:** Phase 1 (agent prompt engineering and cascade logic). Must be testable before full TUI integration.

---

## Minor Pitfalls

Issues that cause friction or require small fixes but are not project-threatening.

---

### Pitfall 12: asyncio.TaskGroup Cancels ALL Tasks on First Exception

**What goes wrong:** In Python 3.11+, `asyncio.TaskGroup` cancels all remaining tasks when any single task raises an exception. For AlphaSwarm, if 1 out of 16 parallel Ollama requests fails (timeout, OOM), the TaskGroup cancels the other 15 successful/in-progress requests and wraps everything in an `ExceptionGroup`.

**Prevention:**
1. Wrap individual agent coroutines in try/except that catches and logs errors instead of propagating:
   ```python
   async def safe_agent_process(agent):
       try:
           return await process_agent(agent)
       except Exception as e:
           logger.error(f"Agent {agent.id} failed: {e}")
           return AgentResult.error(agent.id, str(e))
   ```
2. Use `asyncio.gather(*tasks, return_exceptions=True)` instead of TaskGroup when you want partial results from a batch
3. If using TaskGroup, accept that it is all-or-nothing per batch and design batch sizes to minimize blast radius (8-16 agents, not all 100)

**Confidence:** HIGH -- documented Python 3.11+ behavior.

**Phase:** Phase 1 (batch processing logic).

---

### Pitfall 13: Neo4j Composite Index Requires All Properties in Query Filter

**What goes wrong:** AlphaSwarm uses `cycle_id` on relationships for cycle-scoped queries. A composite index on `(cycle_id, round)` is only used if the query filters on BOTH properties. A query filtering only on `cycle_id` will not use the composite index -- it will fall back to a full scan.

**Prevention:**
1. Create separate single-property indexes for properties that are queried independently:
   ```cypher
   CREATE INDEX idx_influenced_by_cycle FOR ()-[r:INFLUENCED_BY]-() ON (r.cycle_id)
   CREATE INDEX idx_influenced_by_round FOR ()-[r:INFLUENCED_BY]-() ON (r.round)
   ```
2. Create the composite index only for queries that always filter on both
3. Always specify `database_` parameter in driver calls to avoid the extra metadata lookup

**Confidence:** HIGH -- documented in Neo4j Cypher manual.

**Phase:** Phase 1 (database schema setup).

---

### Pitfall 14: Ollama Request Queuing Behavior Under OLLAMA_MAX_QUEUE Saturation

**What goes wrong:** When all parallel slots are occupied, Ollama queues incoming requests up to `OLLAMA_MAX_QUEUE` (default: 512). If the queue fills, new requests get 503 errors. More subtly, queued requests add latency that accumulates: if 100 agent requests arrive simultaneously with `OLLAMA_NUM_PARALLEL=8`, the last batch waits for ~12 batches to complete before starting.

**Prevention:**
1. Do not fire all 100 agent requests simultaneously. Use the semaphore to control submission rate to match Ollama's parallel capacity
2. Set `OLLAMA_MAX_QUEUE` to a reasonable value (32-64, not the default 512) so you get fast-fail behavior instead of silent queuing
3. Implement timeout-based retry: if a request has been queued for >30 seconds, cancel and retry

**Confidence:** HIGH -- documented in Ollama configuration.

**Phase:** Phase 1 (Ollama client wrapper).

---

### Pitfall 15: Python 3.12 asyncio.CancelledError Propagation Bug

**What goes wrong:** Python 3.12 has a documented bug where `asyncio.CancelledError` leaks out of `asyncio.TaskGroup` when using eager tasks or when exceptions inside an inner TaskGroup are delayed. This can cause unexpected cancellation of the outer event loop or parent tasks.

**Prevention:**
1. Use Python 3.11 (specified in project requirements) or 3.13+ where the bug is fixed
2. If using 3.12, avoid nesting TaskGroups and be defensive about CancelledError handling
3. Never swallow `asyncio.CancelledError` -- re-raise it after cleanup

**Confidence:** HIGH -- documented in CPython issue tracker (#128588, #133747).

**Phase:** Phase 0 (environment setup). Pin Python version.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation | Severity |
|-------------|---------------|------------|----------|
| Phase 0: Project setup | Ruflo is not a Python library (#3) | Build custom Python orchestrator | Critical |
| Phase 0: Environment | Python version affects asyncio behavior (#15) | Pin Python 3.11 | Minor |
| Phase 1: Ollama integration | Memory budget does not close (#1) | Sequential model loading, reduce NUM_PARALLEL | Critical |
| Phase 1: Ollama integration | Context size mismatch reloads (#2) | Standardize num_ctx via Modelfiles | Critical |
| Phase 1: Ollama integration | Queue saturation under load (#14) | Semaphore-gated submission | Moderate |
| Phase 1: Core asyncio | Task GC Heisenbug (#5) | TaskGroup for all agent processing | Critical |
| Phase 1: Core asyncio | Semaphore permit leak (#8) | Always use `async with` | Moderate |
| Phase 1: Core asyncio | TaskGroup all-or-nothing cancellation (#12) | Wrap agents in try/except | Minor |
| Phase 1: Neo4j integration | AsyncSession sharing (#4) | Session-per-coroutine, use execute_query() | Critical |
| Phase 1: Neo4j integration | Write deadlocks on hot nodes (#6) | Batch writes per round | Critical |
| Phase 1: Neo4j integration | Composite index partial match (#13) | Separate single-property indexes | Minor |
| Phase 1: ResourceGovernor | psutil misleading on Apple Silicon (#9) | Use macOS memory_pressure + Ollama /api/ps | Moderate |
| Phase 1: Agent prompts | Echo chamber consensus (#11) | Differentiated prompts, temperature variance | Moderate |
| Phase 1: TUI | Per-agent UI updates freeze Textual (#7) | Snapshot-based 200ms tick rendering | Moderate |
| Phase 2: Miro | Credit-based rate limiting (#10) | Parse X-RateLimit headers, credit-aware batching | Moderate |

---

## Sources

**Ollama Performance and Memory:**
- [Ollama FAQ](https://docs.ollama.com/faq) -- parallel request and memory configuration
- [How Ollama Handles Parallel Requests](https://www.glukhov.org/post/2025/05/how-ollama-handles-parallel-requests/) -- batching and KV cache allocation
- [Ollama VRAM Requirements Guide](https://localllm.in/blog/ollama-vram-requirements-for-local-llms) -- per-model memory estimates
- [Apple Silicon Limitations with Local LLMs](https://stencel.io/posts/apple-silicon-limitations-with-usage-on-local-llm%20.html) -- Metal GPU memory cap at 75%
- [Preventing Model Swapping in Ollama](https://blog.gopenai.com/preventing-model-swapping-in-ollama-a-guide-to-persistent-loading-f81f1dfb858d) -- KEEP_ALIVE and context mismatch reloads
- [Ollama Model Switching Issues (GitHub #8779)](https://github.com/ollama/ollama/issues/8779) -- concurrent model loading problems

**Neo4j Python Driver:**
- [Neo4j Python Driver Concurrency](https://neo4j.com/docs/python-manual/current/concurrency/) -- session safety rules
- [Neo4j Python Driver Performance](https://neo4j.com/docs/python-manual/current/performance/) -- UNWIND batching, Rust extension, connection pooling
- [Neo4j Concurrent Data Access](https://neo4j.com/docs/operations-manual/current/database-internals/concurrent-data-access/) -- lock contention and deadlock behavior
- [Neo4j Relationship Chain Locks](https://neo4j.com/developer-blog/relationship-chain-locks-dont-block-the-rock/) -- edge creation locking
- [Neo4j asyncio Driver Issue #945](https://github.com/neo4j/neo4j-python-driver/issues/945) -- read() concurrent coroutine error

**Textual TUI:**
- [Textual Workers Guide](https://textual.textualize.io/guide/workers/) -- call_from_thread, UI thread safety
- [The Heisenbug Lurking in Your Async Code](https://textual.textualize.io/blog/2023/02/11/the-heisenbug-lurking-in-your-async-code/) -- Task GC problem
- [Overhead of Python Asyncio Tasks](https://textual.textualize.io/blog/2023/03/08/overhead-of-python-asyncio-tasks/) -- 260K tasks/sec benchmark

**asyncio Patterns:**
- [Mastering asyncio Semaphores](https://medium.com/@mr.sourav.raj/mastering-asyncio-semaphores-in-python-a-complete-guide-to-concurrency-control-6b4dd940e10e) -- permit leak patterns
- [Limiting Concurrency in asyncio](https://death.andgravity.com/limit-concurrency) -- memory management with semaphores
- [asyncio.TaskGroup Pitfalls](https://runebook.dev/en/docs/python/library/asyncio-task/asyncio.TaskGroup.create_task) -- cancellation behavior
- [CPython Issue #128588](https://github.com/python/cpython/issues/128588) -- CancelledError leaking from TaskGroup in 3.12

**Miro API:**
- [Miro API Rate Limiting](https://developers.miro.com/reference/rate-limiting) -- credit tiers and header documentation

**Multi-Agent LLM Systems:**
- [Why Do Multi-Agent LLM Systems Fail? (arxiv:2503.13657)](https://arxiv.org/html/2503.13657v1) -- 18 failure modes across 150+ tasks
- [Ruflo GitHub Repository](https://github.com/ruvnet/ruflo) -- confirms Node.js/TypeScript architecture, not Python

**Ruflo:**
- [Ruflo GitHub](https://github.com/ruvnet/ruflo) -- Node.js 20+ requirement, Claude Code extension
- [Ruflo npm package (claude-flow)](https://www.npmjs.com/package/claude-flow) -- distribution as npm package

**macOS Memory:**
- [psutil macOS Issues (GitHub #1908)](https://github.com/giampaolo/psutil/issues/1908) -- VMS reporting inaccuracies on macOS
