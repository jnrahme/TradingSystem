# Current State

Last updated: 2026-04-03

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
  - it now blocks duplicate entries into the same expiry
  - it now surfaces non-canonical condor structures as alerts instead of silently ignoring them
- A static operator dashboard exists at `apps/dashboard/index.html`
- A broker-scoped dashboard summary is generated at `apps/dashboard/data/summary.json`
- A worker execution lock exists so overlapping runs cannot mutate the same paper state at once
- Reconcile and verify CLI commands now absorb the first useful legacy sync and verification behaviors
- Worktree checkouts can reuse the root `.env.paper.local` for Alpaca paper verification without copying the file into each branch checkout
- A first-pass CI workflow now runs the repo verification script on pushes and pull requests
- Automated verification exists for the first vertical slice:
  - 28 pytest tests currently pass
  - internal-paper run, reconcile, and verify commands pass sequentially
  - Alpaca paper verify passes from a dedicated git worktree
  - repeated internal-paper execute runs still avoid reopening the same condor expiry
  - `bash scripts/verify.sh` now provides one local verification entrypoint for syntax, tests, schema parsing, and internal paper smoke checks

## What Does Not Exist Yet

- Full parity with the legacy `trading` repo
- Full legacy strategy coverage beyond the first options plugin
- Full risk and safety parity beyond the strongest extracted guardrails from `trade_gateway.py` and `mandatory_trade_gate.py`
- Full legacy iron-condor entry-signal and scanner parity, including VIX timing and richer expiry discovery
- Full fill reconciliation, retry, and recovery flows
- A production scheduler/daemon for market-hours autonomous runs
- A replay/backtest lab with promotion scoring
- Multi-broker capability registry beyond the first Alpaca paper adapter
- IBKR and Coinbase adapters
- Full operator workflows for incidents, kill switches, daily reviews, and promotion approvals

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
PYTHONPATH=src python3 -m new_trading_system.cli run-once --broker internal-paper --execute
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
