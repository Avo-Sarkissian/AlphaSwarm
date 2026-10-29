# Evaluation methodology (pre-registered)

> **Status:** pre-registered; no evaluation run is recorded yet. Results: [experiments.md, headline numbers](experiments.md#headline-numbers-v60).

This document fixes, before any evaluation run, what AlphaSwarm's accuracy
evaluation (P7.7) and ablations (P7.8) measure and how the results are read.
`alphaswarm.evaluation` and the scripts in `eval/` implement every rule
(`docs/DECISIONS.md#adr-eval-harness`); results go to `docs/experiments.md`.
After the registration record (§11) is committed, §1-9 and §11 do not change;
any departure is listed in §10 with its reason.

## 1. Question

Does the 100-agent swarm's final consensus predict the direction of a stock's
abnormal return after a market rumor better than cheaper ways of asking the same
local worker model, and is that edge robust to memorization?

## 2. Events

- 15-20 historical public rumor or news events in `eval/events.jsonl`: event id,
  UTC timestamp to the minute (wire time), rumor text as reported, one primary
  US-listed ticker, a benchmark (a broad-market index ETF unless a sector ETF is more appropriate),
  a category, the post-cutoff flag and an anonymized rumor.
- At least 40% are dated after the worker model's release date (`post_cutoff`).
- Events are chosen from public news by these criteria before any price reaction
  is looked up, never from the owner's holdings; at most 5 per category; every
  event is at least 10 days old when labelled.
- The anonymized rumor replaces company, product and people names and the ticker
  with neutral descriptors and keeps every other fact.
- `uv run python eval/run_eval.py check` enforces every rule above that a script
  can check.

## 3. Outcome labels (`eval/label_outcomes.py`)

- Base close: the last session whose close (16:00 America/New_York, or 13:00 on an
  NYSE early-close day) is at or before the event timestamp. Day h is the h-th session after it, over the trading days
  the ticker and benchmark series share.
- Abnormal return over h ∈ {1, 5}: ticker return minus benchmark return
  (market-adjusted model, beta 1) on auto-adjusted closes.
- Volatility scale σ: sample standard deviation of the 20 daily abnormal returns
  ending at the base close (floor 0.0001).
- Label: "flat" when |abnormal return| < 0.5 · σ · √h, otherwise "up" or "down".
- Primary horizon: 1 day. Secondary: 5 days.

## 4. Point-in-time context

- Every swarm run uses `alphaswarm run --context-fixture eval/fixtures/<event_id>.json`:
  the last close and volume at or before the event timestamp (split-adjusted
  Yahoo close) and, where curated, up to 5 headlines published before it (the most
  recent ones; the market block renders at most 5 per entity). No
  fundamentals: the providers only expose current values.
- The anonymized variant uses `eval/fixtures/<event_id>.anon.json`: the same
  numbers under the label "Subject company", without headlines.
- Known limitation: a later stock split changes the split-adjusted close; returns
  and labels are unaffected.
- Known limitation: the anonymized variant keeps the real price and volume, which a
  model could use to recognise a well-known stock, so the named vs anonymized
  comparison (§8) bounds name-based memorization only.

## 5. Forecasters

Each forecaster produces a score S ∈ [-1, 1] per run; P(up) = (1 + S) / 2.

| Name | Score | Source |
|---|---|---|
| swarm (primary) | final-round net score, headcount weighting (`alphaswarm.consensus`) | stored decisions |
| swarm_reach | final-round net score, reach weighting | stored decisions |
| swarm_ex_narrators, narrators_only | headcount net score without / with only the Narrators bracket (the deliberate second-order bracket, scored separately) | stored decisions |
| r1_only | Round 1 headcount net score of the same cycles | stored decisions |
| orchestrator | the orchestrator's `overall_sentiment` | Cycle node |
| single_k5 | mean signed confidence of 5 samples of one neutral analyst prompt on the worker | `eval/baselines.py single` |
| self_consistency | the same over 100 × rounds samples (compute-matched to one swarm cycle) | `eval/baselines.py sc` |

- Swarm and Round 1 scores need at least 50 valid (non-PARSE_ERROR) votes in
  their round; narrators_only needs 4. single_k5 needs 3 valid samples,
  self_consistency half of k.
- Baseline prompt: a neutral equity-analyst system prompt plus the shared JSON
  output instructions, the same fenced market block, the rumor as the user
  message, temperature 0.57 (the swarm's headcount-weighted mean bracket
  temperature), seeds derived from the run seed.

## 6. Runs and aggregation

- Seeds 1-3 map to `sim_seed` 2101-2103. Experiment tags: `p77.swarm` (named,
  seeds 1-3) and `p77.anon` (anonymized, seed 1).
- Swarm runs use 2 rounds (gate G-23). Every arm runs with `control_fraction = 0`
  (no P7.3 control holdout, so every agent of the swarm under test sees peers; the
  peer-free contrast is the `peer_none` arm). Every other setting is the product
  default frozen at registration in `eval/registered_simulation.json` (§11).
- A forecaster's score for an event is the mean of its run scores over seeds.
- Excluded and counted: cycles that are not `complete`; cycles whose run manifest
  disagrees with the planned arm (rounds, seed, tag, or settings compared with the
  registered defaults plus the arm's knobs); cycles whose
  market block differs from the majority block of their event and variant. A
  re-run replaces an older cycle of the same arm, event and seed.

## 7. Metrics and the claim rule

- Directional events: label up or down at the horizon.
- Hit rate on directional events (S > 0 predicts up, S < 0 down, S = 0 is a miss)
  with a Wilson 95% interval.
- Brier score and log loss (P clipped to [0.01, 0.99]) of P(up) on directional
  events.
- Spearman ρ between S and the abnormal return over all labelled events;
  3-class accuracy of the net-score lean (deadband 0.15) against up/flat/down.
- Reliability diagram: 5 equal-width bins of P(up).
- Comparisons: per-event Brier difference swarm − baseline, paired bootstrap over
  events (2000 resamples, 95% percentile interval with linear interpolation,
  RNG seeded with blake2b of 20261003 and the table cell name).
- **Claim rule (primary):** "the swarm beats baseline X" only when the 1-day
  Brier-difference interval lies entirely below 0; "worse" when entirely above 0;
  otherwise "inconclusive". The two required baselines are orchestrator and
  r1_only; single_k5 and self_consistency are reported when run.

## 8. Leakage controls

- Post-cutoff split: hit rate and Brier reported separately for post- and
  pre-cutoff events.
- Named vs anonymized (swarm, seed 1): mean |S_named − S_anonymized| and the Brier
  difference anonymized − named, paired over events.
- Memorization probe: one worker call per event (named rumor, date and ticker, no
  market context, temperature 0) asking whether it remembers the 5-day move;
  reported as recall rate and recall accuracy per split. Events recalled with the
  correct direction are "suspect", and the swarm row is repeated without them.

## 9. Ablations (P7.8) and gate rules

- Subset: 5 events drawn with `random.Random(20261003)` from the sorted event ids;
  seeds 1-3; 2 rounds except where Round 3 is the variable.

| Arm | Change | Rounds | Compared with |
|---|---|---|---|
| rounds3 | none | 3 | swarm, and Round 3 vs Round 2 inside the same cycles |
| peer_random | `peer_strategy = random` | 2 | swarm |
| peer_none | `peer_strategy = none` | 2 | swarm |
| boost_0 | `personal_boost = 0.0` | 3 | rounds3 |
| boost_005 | `personal_boost = 0.05` | 3 | rounds3 |
| own_prior_off | `own_prior_memory = false` | 2 | swarm |
| uniform_temp | `uniform_temperature = 0.57` | 2 | swarm |
| private_headlines (only if gate G-19 = A) | `private_headlines = true` | 2 | swarm |

- Per (event, seed) pair: differences in final net score, mean |Δ net score|,
  lean agreement, final-round entropy, flips per agent per peer round, citation
  Gini, distinct peers shown, 1-day Brier (directional events) and wall seconds;
  cluster bootstrap over events.
- **G-16 (default rounds):** recommend 2 rounds when, inside the rounds3 cycles,
  the 95% upper bound of mean |S₃ − S₂| is at most 0.10, the lean agrees in at
  least 80% of pairs, and the Brier difference S₃ − S₂ has a lower bound of at
  least −0.05 (or there are no directional pairs); otherwise keep 3.
- **G-15 (R3 personal boost):** recommend changing the default from 0.3 to
  v ∈ {0, 0.05} when v's 95% interval for the difference in Round 3 distinct peers
  shown lies entirely above 0 and its 1-day Brier-difference upper bound is at
  most 0.05; if both qualify, the one with the larger mean gain; otherwise keep 0.3.
- **G-20 (DECISION_SCHEMA_V2):** recommend V2 when at least 50% of events have a
  swarm lean of hold (|S| ≤ 0.15) while the swarm's directional hit rate is above
  0.5; otherwise keep the current schema.
- The owner decides every gate; the recommendation and the decision are both
  recorded in `docs/experiments.md`.

## 10. Deviations from pre-registration

None.

## Limitations

- **A simulation, not a market.** The swarm models who forms and spreads opinions about a
  rumor; passive capital and market makers are excluded on purpose
  ([adr-swarm-composition-v2](DECISIONS.md#adr-swarm-composition-v2)). Signals are
  opinions, not trades, and nothing here is investment advice.
- **Public information only.** Agents see the rumor, injected shocks, public prices and
  headlines for named tickers in the configured rounds, and from Round 2 a sample of peer
  rationales and their own previous position. There is no private information unless the
  private-headlines experiment flag is on.
- **Small samples.** The event set and seed counts are small, so read every number with its
  confidence interval. Ablations use a subset of events, with 2 rounds wherever Round 3
  is not the variable (§9).
- **Models and decoding.** Results hold for the recorded models and prompts (each cycle's
  run manifest). Seeds make peer selection and control assignment exact, but batched
  decoding on Ollama (`OLLAMA_NUM_PARALLEL` above 1) is not bit-exact, so two runs with the
  same seed can differ in a few decisions.
- **Leakage.** A model may know an event's outcome from training. The evaluation reports the
  post-cutoff subset and the anonymized-rumor variant separately (§8); treat pre-cutoff
  results as an upper bound.
- **Labels.** Outcomes are abnormal returns against a benchmark at fixed horizons with a
  volatility-scaled flat band (§3); other horizons or bands can change a verdict.

## Reproduce

1. Every cycle stores its run manifest (`run_manifest_json` on the Cycle node): models and
   digests, prompt hashes, settings and seeds. List cycles with `uv run alphaswarm cycles list`
   and export one with `uv run alphaswarm cycles export CYCLE_ID -o cycle.json`; the export
   includes the manifest when one was stored.
2. Re-run a configuration by setting the manifest's settings as `ALPHASWARM_SIMULATION__*`
   variables (including `SIM_SEED` and `EXPERIMENT_TAG`) and running
   `uv run alphaswarm run "RUMOR"`.
3. Rebuild the comparison tables from stored cycles with
   `uv run python scripts/compare_cycles.py --group-by experiment_tag,worker_model --markdown`
   and the control comparison with `uv run python scripts/peer_effect.py` (see `--help`).
4. Rebuild the evaluation: `uv sync --group eval`, then `uv run python eval/label_outcomes.py`
   and `uv run python eval/run_eval.py` (see `--help` for each). Every results table in
   [experiments.md](experiments.md) names the command and cycle ids it came from.
