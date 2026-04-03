# Dashboard

Owns the analytical UI for strategy scorecards, portfolio health, execution quality, promotion state, and incident review.

This application is read-only against curated platform views. It does not place trades.
Dashboard assets live here.

Current vertical-slice behavior:

- the paper worker writes a broker-scoped summary file to `apps/dashboard/data/summary.json`
- `apps/dashboard/index.html` renders that summary as a lightweight operator dashboard
- `PYTHONPATH=src python3 -m new_trading_system.cli dashboard` prints the same JSON summary in the terminal

If you want the HTML dashboard to load the JSON locally, serve the repo root with a simple HTTP server instead of opening the file directly in a browser.

