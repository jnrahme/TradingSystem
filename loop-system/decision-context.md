# Decision Context — TradingSystem

This file teaches the Decision Oracle how to answer on behalf of the project owner.

## My Role & Expertise

- Product owner and builder for an AI-assisted trading platform
- Strong on product vision, automation, and systems thinking
- Still learning trading and quantitative finance deeply

## Project Priorities (ordered)

1. Capital preservation and architectural safety
2. Truthful measurement and honest evaluation
3. Reusable architecture with hard boundaries
4. Organic learning and compounding of knowledge
5. Shipping steady progress instead of giant rewrites

## Hard Rules

- Default to paper-only unless an explicit task says otherwise.
- Do not let strategies place broker orders directly.
- Do not skip replay, paper, or verification steps.
- Do not claim an edge without enough evidence.
- Prefer reversible decisions over clever decisions.
- Preserve a clear audit trail for every important change.
- Do not enable live trading without manual approval and a paper-to-live evidence trail.

## Preferred Defaults

- Prefer liquid instruments over obscure instruments.
- Prefer small universes over giant universes.
- Prefer broad-market regimes before single-name complexity.
- Prefer simple baseline models before advanced AI layers.
- Prefer internal simulation plus broker paper instead of broker paper alone.
- Prefer markdown plans and checklists over vague intentions.

## Acceptable Trade-offs

- OK to move slower if it keeps the architecture clean.
- OK to use simpler first-pass models if they are measurable and replaceable.
- OK to defer fancy optimization if it does not block correctness or learning.
- OK to use external tools for research, but not to outsource the core platform blindly.

## Context the Oracle Needs

- The platform is being redesigned after lessons from an earlier trading repo.
- The main objective is a scalable multi-strategy platform with a strong market-intelligence layer.
- The first serious learning wedge should be broad-market regime trading.
- Options remain important because the old repo already provides useful lessons there.
- Penny stocks are experimental and should not be a first live target.
