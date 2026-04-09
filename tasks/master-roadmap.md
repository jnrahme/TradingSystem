# TradingSystem Master Roadmap

## Phase 0 — Foundation

- [ ] Create a project-wide architecture decision record for canonical state, risk path, and strategy contract.
- [ ] Add CI checks for schema validation, markdown lint, Python syntax, and basic repo hygiene.
- [x] Add a first-pass CI workflow for syntax, tests, schema JSON parsing, and internal paper smoke verification.
- [ ] Define the canonical event envelope and market-state schemas.
- [ ] Define the canonical ledger schema and promotion-stage model.
- [ ] Define the paper-only operating policy and paper-to-live graduation scorecard.
- [x] Add a repo-wide default that every strategy manifest starts paper-only and requires manual live approval.
- [x] Add environment templates for local research, paper trading, and future live deployment.

## Phase 1 — Loop System Adaptation

- [x] Adapt the loop system so sequential mode supports Codex, Claude, and OpenCode backends.
- [x] Replace UE5-specific agent prompts with trading-specific audit, todo, review, and orchestrator agents.
- [x] Write a project decision context tuned for trading, research, risk, and reversibility.
- [x] Add a loop-system README with safe usage examples for backlog execution.
- [x] Validate the loop scripts with help commands and a dry-run workflow.

## Phase 2 — Market Intelligence Core

- [ ] Define the daily market note data model.
- [ ] Define the market regime label taxonomy.
- [ ] Build a macro-event ingestion plan covering Fed, inflation, labor, GDP, Treasury, and earnings.
- [ ] Define the first cross-asset watchlist and rationale.
- [ ] Create a market-state feature inventory document.
- [ ] Implement placeholder schemas for event intelligence and market intelligence outputs.

## Phase X — Legacy Extraction Program

- [x] Write the legacy extraction master plan and classification rules.
- [x] Publish a human-friendly HTML portal explaining the moving pieces and migration program.
- [x] Add a current-state truth document for the app.
- [x] Add a documentation-freshness contract and repo-level LLM instructions.
- [x] Inventory every high-value legacy strategy, script family, and workflow into extract / redesign / reference-only / discard buckets.
- [x] Port the strongest risk rules from `trade_gateway.py` into the new risk engine.
- [x] Port the strongest opening-versus-closing order safety rules from `mandatory_trade_gate.py`.
- [x] Collapse useful legacy verification and sync scripts into a smaller new CLI surface.
- [ ] Finish Alpaca order lifecycle parity with stronger fill reconciliation, stale-order cleanup policy, and recovery hooks.
- [ ] Finish legacy iron-condor lifecycle parity beyond the current entry-only slice.
- [x] Add first-pass legacy iron-condor lifecycle controls: profit/stop/DTE exits, duplicate-expiry blocking, and broken-structure detection.
- [x] Improve legacy iron-condor entry selection so the strategy searches the DTE window for the next available expiry with contracts.
- [x] Add a first-pass VIX regime gate to the legacy iron-condor entry path when volatility quotes are available.
- [ ] Define the reduced workflow set that replaces the useful legacy GitHub Actions without recreating the old workflow sprawl.

## Phase 3 — Research Lab

- [ ] Build a replay harness specification for broad ETF regime strategies.
- [x] Add a first synthetic demo replay harness for the current options strategy so exit logic can be exercised deterministically.
- [x] Add a first bar-driven historical backtest for the current options strategy using real SPY bars plus modeled option pricing.
- [ ] Define baseline strategies for momentum, mean-reversion, and event response.
- [ ] Add a result schema for backtest / replay outputs.
- [ ] Define evaluation metrics for regime quality, expectancy, drawdown, and live drift.
- [ ] Create the first research notebook or script scaffold for broad-market strategy evaluation.
- [x] Add a first-pass paper strategy scorecard so runtime claims are tied to ledger-observed evidence instead of guesses.
- [x] Add a first-pass promotion gate that evaluates replay and paper evidence against strategy-defined thresholds.
- [x] Add an autonomous market-hours supervisor with halt/status/heartbeat primitives and a service-wrapper example.
- [x] Add first-class CLI controls for autonomous runtime status and halt/resume operations.
- [x] Align the live DTE window to the enforced 11-52 entry range so new entries stay outside the 10-DTE forced-exit zone.
- [x] Extend the live open-condor cap to 8 so the runtime can use that very near weekly rung without displacing the existing ladder.
- [x] Merge broker-backed same-day order history into live intraday risk guardrails so daily structure limits survive local-ledger drift.
- [x] Raise the same-day structure cap to match the live weekly ladder while keeping cumulative risk as the main exposure control.
- [x] Lower the minimum credit floor to 0.40 so the near-expiry weekly rung is available without degrading constrained replay quality.
- [x] Tolerate tiny option mark drift in live reconciliation so harmless quote jitter does not degrade the autonomous runtime.
- [x] Raise the DTE exit threshold to 10 because it left constrained replay unchanged while making the near-expiry live condor eligible to close sooner.
- [x] Lower the live take-profit target to 2.5% after constrained multi-window replay showed it stayed loss-free while shortening holding time further.

## Phase 4 — Data Stack

- [ ] Choose the low-cost initial market data path for ETF and crypto research.
- [ ] Choose the initial news / event ingestion path.
- [ ] Define archival storage layout for raw events, normalized features, and replay bundles.
- [ ] Define data-quality checks for stale data, gaps, split handling, and schema drift.

## Phase 5 — Strategy Families

- [ ] Create the `broad-market-regime` strategy family folder and manifest.
- [ ] Create the `defined-risk-options` strategy family folder and manifest.
- [ ] Create the `crypto-regime` strategy family folder and manifest.
- [ ] Write acceptance rules for when a strategy may graduate from replay to paper.
- [ ] Write acceptance rules for when a strategy may graduate from paper to live.

## Phase 6 — Simulation and Brokers

- [x] Define the internal paper broker contract.
- [ ] Define the broker capability registry.
- [x] Build a first pass on Alpaca adapter requirements.
- [x] Add account-scoped runtime isolation so multiple paper accounts can run independently from one repo checkout.
- [x] Add a sequential multi-account runner so named paper accounts can auto-cycle from one CLI command.
- [ ] Build a first pass on IBKR adapter requirements.
- [ ] Build a first pass on Coinbase adapter requirements.
- [ ] Write reconciliation requirements for broker fills versus canonical ledger.
- [x] Add first-pass broker-versus-ledger reconcile and verify commands with stale-order checks.
- [x] Ship the first runnable paper-only vertical slice with worker, ledger, internal paper broker, Alpaca paper adapter, and legacy options strategy plugin.

## Phase 7 — Dashboard and Operators

- [ ] Define the dashboard read models for strategy leaderboard, portfolio health, and incidents.
- [ ] Define promotion and kill-switch workflows for the operator console.
- [ ] Define daily review and post-trade attribution reports.
- [x] Build the first dashboard summary file and static operator view for broker-scoped paper results.

## Phase 8 — Live Readiness

- [ ] Define canary capital rules.
- [ ] Define hard kill conditions for data, broker, and strategy drift.
- [ ] Define a pre-live checklist for the first deployed strategy.
- [ ] Define rollback and incident runbooks.
