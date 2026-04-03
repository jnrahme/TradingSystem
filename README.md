# NewTradingSystem

This repository is scaffolded as a broker-agnostic, multi-strategy trading platform.

Start with `index.html` for the full redesign brief. The repo is organized so the trading system, strategies, reusable SDKs, dashboards, schemas, and infrastructure can evolve independently.

Core operating assumption:

- Strategies never place broker orders directly.
- The platform owns execution, risk, reconciliation, persistence, and promotion gates.
- Every strategy must pass replay, internal paper trading, and broker-paper validation before live capital is increased.

Top-level layout:

- `apps/`: dashboard and operator-facing interfaces
- `services/`: platform runtime services
- `packages/`: reusable SDKs, schemas, and shared types
- `strategies/`: pluggable strategy families
- `schemas/`: versioned JSON contracts
- `infra/`: deployment and environment assets
- `tests/`: replay and integration verification harnesses
