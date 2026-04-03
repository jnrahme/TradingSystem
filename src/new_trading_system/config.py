from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def apply_env_file(path: Path) -> dict[str, str]:
    loaded = load_env_file(path)
    for key, value in loaded.items():
        os.environ.setdefault(key, value)
    return loaded


@dataclass(slots=True)
class RuntimeConfig:
    project_root: Path
    state_db_path: Path
    dashboard_summary_path: Path
    strategy_state_dir: Path
    internal_paper_state_path: Path
    worker_lock_path: Path
    default_broker: str
    alpaca_api_key: str | None
    alpaca_api_secret: str | None
    alpaca_trading_base_url: str
    alpaca_data_base_url: str
    paper_only: bool = True

    @classmethod
    def from_env(cls, root: Path | None = None) -> "RuntimeConfig":
        root_path = root or project_root()
        apply_env_file(root_path / ".env.paper.local")

        state_db_path = root_path / "var" / "trading-state.sqlite3"
        dashboard_summary_path = root_path / "apps" / "dashboard" / "data" / "summary.json"
        strategy_state_dir = root_path / "var" / "strategy-state"
        internal_paper_state_path = root_path / "var" / "internal-paper-state.json"
        worker_lock_path = root_path / "var" / "worker.lock"
        state_db_path.parent.mkdir(parents=True, exist_ok=True)
        dashboard_summary_path.parent.mkdir(parents=True, exist_ok=True)
        strategy_state_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            project_root=root_path,
            state_db_path=state_db_path,
            dashboard_summary_path=dashboard_summary_path,
            strategy_state_dir=strategy_state_dir,
            internal_paper_state_path=internal_paper_state_path,
            worker_lock_path=worker_lock_path,
            default_broker=os.environ.get("NTS_DEFAULT_BROKER", "internal-paper"),
            alpaca_api_key=os.environ.get("ALPACA_PAPER_API_KEY"),
            alpaca_api_secret=os.environ.get("ALPACA_PAPER_API_SECRET"),
            alpaca_trading_base_url=os.environ.get(
                "ALPACA_PAPER_API_BASE_URL", "https://paper-api.alpaca.markets/v2"
            ),
            alpaca_data_base_url=os.environ.get(
                "ALPACA_DATA_API_BASE_URL", "https://data.alpaca.markets"
            ),
        )
