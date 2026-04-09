# Research Lab

Owns replay, backtesting, shadow runs, parameter experiments, and strategy evaluation outputs.

It uses the same contracts as production so research and runtime do not drift apart.

Current vertical-slice behavior:

- `PYTHONPATH=src python3 -m new_trading_system.cli scorecard --account <id> --broker <name>` prints the current paper evidence scorecard from the canonical ledger
- the scorecard reports observed fills, open P/L, exit reasons, and explicit blockers when replay or closed-trade evidence is still missing
- `PYTHONPATH=src python3 -m new_trading_system.cli replay --strategy legacy-iron-condor` runs a synthetic internal-paper scenario set through the production strategy/runtime/execution path
- `PYTHONPATH=src python3 -m new_trading_system.cli replay --scenario-set historical-bars --days 90 --strategy legacy-iron-condor` runs a bar-driven historical backtest through the research-lab path
- this replay is deterministic and useful for exercising exits and invariants, but it is not a substitute for historical backtests or promotion-grade replay coverage
- the historical-bars replay is the first real profitability-evidence step: it uses historical SPY bars from Alpaca, modeled option pricing, and a realized-volatility proxy instead of historical option-chain quotes
- the historical-bars replay now bounds exits to contract expiry and skips trades when future bars are insufficient, which keeps long-window replay aggregates from being inflated by impossible holds across data gaps
- the historical-bars replay now also respects the live strategy's open-structure cap and duplicate-expiry rules, so it no longer overstates trade frequency relative to the real runtime
- the live Alpaca paper runtime now reuses that realized-volatility proxy when direct `VIX` quotes are unavailable, so the runtime and research gate on volatility in a more consistent way
- replay outputs persist under `var/replay/`, and the scorecard uses those saved reports to mark replay evidence as present for matching strategies
- `PYTHONPATH=src python3 -m new_trading_system.cli promotion --account <id> --broker <name> --strategy legacy-iron-condor` evaluates whether the saved replay and paper evidence are strong enough to advance the strategy to manual live review
- if the sibling legacy repo exists, the research/evidence surfaces can also show `trading/data/trades.json` as legacy reference evidence, but that data stays labeled as calibration only and does not auto-pass the current-system gate
