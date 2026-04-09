# Replay Tests

These tests validate strategies and execution logic against deterministic historical event streams.

Replay should be the first gate every strategy has to pass.

Current vertical-slice behavior:

- `tests/replay/test_demo_replay.py` validates the first synthetic replay harness for `legacy-iron-condor`
- this harness is deterministic and exercises profit-target, stop-loss, and DTE exits through the production strategy/runtime/execution stack
- `tests/replay/test_historical_backtest.py` validates the first historical-bars replay path for `legacy-iron-condor`
- this path uses real historical bar shapes with modeled option pricing; it is more honest than the demo replay, but still not a quote-by-quote options-chain replay
