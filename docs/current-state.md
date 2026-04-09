# Current State

Last updated: 2026-04-07

This document is the plain-English truth layer for `NewTradingSystem`.

## What Exists Right Now

- A runnable paper-first worker exists in `src/new_trading_system/services/worker.py`
- The worker can run against:
  - the internal simulator in `src/new_trading_system/adapters/internal_paper.py`
  - Alpaca paper trading in `src/new_trading_system/adapters/alpaca_paper.py`
- A clean execution path exists:
  - strategy plugin
  - strategy runtime
  - risk engine with legacy-derived whitelist, daily-loss, intraday, position-stacking, and cumulative-risk guardrails
  - execution engine with ledger-backed intraday metrics
  - reconciliation service with broker-versus-ledger verification and stale-order checks
  - canonical ledger
  - dashboard summary
- One extracted strategy exists:
  - `legacy-iron-condor`
  - it now manages profit-target, stop-loss, and DTE exits
  - it now searches the configured DTE window for the next available expiry with contracts instead of assuming a single target Friday
  - it now applies a basic VIX regime gate when a VIX quote is available and degrades to an informational alert when that quote is unavailable
  - it now blocks duplicate entries into the same expiry
  - it now surfaces non-canonical condor structures as alerts instead of silently ignoring them
- A static operator dashboard exists at `apps/dashboard/index.html`
- A dashboard summary is generated at `apps/dashboard/data/summary.json`, with named account summaries under `apps/dashboard/data/accounts/` and a latest fleet summary at `apps/dashboard/data/accounts/summary.json`
- A worker execution lock exists so overlapping runs cannot mutate the same paper state at once
- Named runtime accounts can now isolate their own worker lock, SQLite state, strategy state, internal paper state, dashboard summary, and optional Alpaca paper credentials via `--account <id>`
- A `run-accounts` CLI path can now execute multiple named accounts sequentially in one command while preserving those per-account boundaries
- `run-loop` and `run-accounts` can now keep cycling with `--forever` for unattended paper execution until the process is stopped
- An `autonomous-runner` CLI path now supervises multi-account paper execution with market-hours gating, a halt file, runtime status/heartbeat files, and optional post-cycle reconcile/verify hooks
- `autonomous-status`, `autonomous-halt`, and `autonomous-resume` now expose first-class operator controls for that autonomous runtime
- A `scorecard` CLI path can now summarize observed paper evidence from the canonical ledger, including fills, open P/L, exit reasons, and explicit blockers like missing replay data
- A `replay` CLI path now runs a first synthetic internal-paper scenario set for `legacy-iron-condor`, covering profit-target, stop-loss, and DTE exits through the production strategy/runtime/execution path
- A `replay --scenario-set historical-bars` path now runs a first bar-driven backtest for `legacy-iron-condor` using real historical SPY daily bars, modeled options pricing, and a realized-volatility proxy for the VIX gate
- The historical-bars replay now enforces expiry-bounded exits and skips trades with insufficient future bars, so long-window replay results no longer include impossible post-expiry holds
- The historical-bars replay now also enforces the live strategy's open-structure cap and duplicate-expiry blocking, so replay trade counts match the actual strategy contract more closely
- The live Alpaca paper adapter now falls back to a realized-volatility proxy for the VIX gate when direct `VIX` quotes are unavailable
- replay reports are now persisted under `var/replay/`, and `scorecard` consumes those saved reports when deciding whether replay evidence exists for a strategy
- A `promotion` CLI path now evaluates replay and paper evidence against strategy-defined thresholds and reports whether a strategy is still blocked or ready for manual live review
- `scorecard` and `promotion` now also surface legacy closed-trade evidence from a sibling `trading/data/trades.json` as labeled reference data without counting it as current-system readiness proof
- The live legacy iron condor runtime now permits up to **8** concurrent structures, giving the runtime one more slot for a very near weekly expiry rung without degrading the constrained replay profile
- The live legacy iron condor entry window now spans **11-52 DTE**, matching the enforced rule that new entries stay outside the 10-DTE forced-exit zone
- The live risk engine now merges broker-backed same-day orders into its daily structure/fill guardrails, so intraday limits remain enforced even if the local ledger is sparse
- The live risk policy now allows up to **8** same-day structures for the weekly condor ladder, while cumulative risk remains the primary exposure cap
- The live iron condor minimum credit floor is now **0.40**, allowing the near-expiry weekly rung without degrading the constrained replay aggregates
- The live iron condor take-profit target is now **2.5%**, chosen because it preserved the clean constrained replay profile while shortening holding time further and bringing the live paper book closer to real exits
- The live iron condor DTE exit threshold is now **10 DTE**, because that left the constrained replay unchanged while allowing the near-expiry live condor to qualify for exit sooner
- Live reconciliation now tolerates tiny option mark drift so the autonomous runtime stays healthy when broker and ledger marks differ by only trivial quote noise
- Reconcile and verify CLI commands now absorb the first useful legacy sync and verification behaviors
- Worktree checkouts can reuse the root `.env.paper.local` for Alpaca paper verification without copying the file into each branch checkout
- A first-pass CI workflow now runs the repo verification script on pushes and pull requests
- Automated verification exists for the first vertical slice:
  - the current pytest suite passes
  - internal-paper run, reconcile, and verify commands pass sequentially
  - Alpaca paper verify passes from a dedicated git worktree
  - repeated internal-paper execute runs still avoid reopening the same condor expiry
  - `bash scripts/verify.sh` now provides one local verification entrypoint for syntax, tests, schema parsing, and internal paper smoke checks

## What Does Not Exist Yet

- Full parity with the legacy `trading` repo
- Full legacy strategy coverage beyond the first options plugin
- Full risk and safety parity beyond the strongest extracted guardrails from `trade_gateway.py` and `mandatory_trade_gate.py`
- Full legacy iron-condor entry-signal and scanner parity, including richer VIX timing and fuller scanner heuristics beyond the current expiry search and simple VIX band gate
- Full fill reconciliation, retry, and recovery flows
- A fuller production scheduler/daemon story beyond the current autonomous runner CLI plus systemd example
- A full historical options-chain replay/backtest lab with promotion scoring beyond the current bar-driven modeled backtest
- Multi-broker capability registry beyond the first Alpaca paper adapter
- A richer multi-account scheduler/operator view beyond the basic sequential `run-accounts` CLI path
- IBKR and Coinbase adapters
- Full operator workflows for incidents, kill switches, daily reviews, and promotion approvals beyond the current evidence-based CLI gate

## Why The Old Repo Is So Much Bigger

The legacy repo is large mostly because of accumulated history and artifacts, not just runtime code.

Measured on 2026-04-03:

- Legacy repo size: about `1.2G`
- New repo checkout remains in the single-digit megabytes before counting extra local worktrees
- Legacy `.git`: about `396M`
- Legacy `data/`: about `257M`
- Legacy `.worktrees`: about `279M`
- Legacy `docs/`: about `270M`

Code-scale comparison:

- Legacy repo Python source files in `src`: `197`
- Legacy repo Python scripts in `scripts`: `135`
- Legacy repo Python tests: `211`
- Legacy repo workflows: `90`
- New repo Python source files: `21`
- New repo Python tests: `8`

The new repo is intentionally smaller because it is rebuilding the useful behavior on cleaner boundaries instead of copying the old operational sprawl.

## Current Architecture That Is Real

```text
CLI / Worker
  -> Control Plane Registry
  -> Strategy Runtime
  -> Risk Engine
  -> Execution Engine
  -> Broker Adapter
  -> Reconciliation Service
  -> Portfolio Ledger
  -> Dashboard Summary
```

## Current Entry Points

```bash
cd /Users/joeyrahme/GitHubWorkspace/NewTradingSystem
python3 -m pip install -e ".[dev]"
PYTHONPATH=src python3 -m new_trading_system.cli run-once --broker internal-paper
PYTHONPATH=src python3 -m new_trading_system.cli run-loop --account primary --broker internal-paper --execute --forever --interval-seconds 60
PYTHONPATH=src python3 -m new_trading_system.cli run-once --broker internal-paper --execute
PYTHONPATH=src python3 -m new_trading_system.cli run-accounts --account primary --account swing-two --broker internal-paper --execute
PYTHONPATH=src python3 -m new_trading_system.cli run-accounts --account primary --account swing-two --broker internal-paper --execute --forever --interval-seconds 60
PYTHONPATH=src python3 -m new_trading_system.cli autonomous-runner --account primary --broker internal-paper --execute --forever --interval-seconds 300 --verify-after-cycle
PYTHONPATH=src python3 -m new_trading_system.cli scorecard --account primary --broker internal-paper
PYTHONPATH=src python3 -m new_trading_system.cli replay --strategy legacy-iron-condor
PYTHONPATH=src python3 -m new_trading_system.cli replay --scenario-set historical-bars --days 90 --strategy legacy-iron-condor
PYTHONPATH=src python3 -m new_trading_system.cli promotion --account primary --broker internal-paper --strategy legacy-iron-condor
PYTHONPATH=src python3 -m new_trading_system.cli reconcile --broker internal-paper
PYTHONPATH=src python3 -m new_trading_system.cli verify --broker internal-paper
PYTHONPATH=src python3 -m new_trading_system.cli run-once --broker alpaca-paper
PYTHONPATH=src python3 -m new_trading_system.cli verify --broker alpaca-paper
PYTHONPATH=src python3 -m new_trading_system.cli dashboard
pytest -q
```

## Source Of Truth Documents

- `README.md`: top-level usage and feature surface
- `docs/plans/2026-04-03-legacy-extraction-master-plan.md`: migration program
- `docs/legacy-inventory.md`: concrete extraction buckets and examples
- `docs/legacy-extraction-portal.html`: human-friendly architecture and migration portal
- `tasks/master-roadmap.md`: backlog and status movement
- `AGENTS.md`: LLM and engineering rules for documentation freshness

## Update Rule

If the code changes in a way that affects this document, update this file in the same change.
