from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalize_account_id(raw_value: str | None) -> str:
    value = (raw_value or "").strip().lower()
    if not value:
        return "default"
    normalized = re.sub(r"[^a-z0-9_-]+", "-", value).strip("-_")
    return normalized or "default"


def account_env_prefix(account_id: str) -> str:
    fragment = re.sub(r"[^A-Z0-9]+", "_", account_id.upper()).strip("_")
    return f"NTS_ACCOUNT_{fragment}_"


def resolve_account_env(
    account_id: str,
    scoped_key: str,
    fallback_key: str | None = None,
    default: str | None = None,
) -> str | None:
    scoped_name = f"{account_env_prefix(account_id)}{scoped_key}"
    if scoped_name in os.environ:
        return os.environ[scoped_name]
    if fallback_key and fallback_key in os.environ:
        return os.environ[fallback_key]
    return default


def runtime_paths_for_account(
    root: Path, account_id: str
) -> tuple[Path, Path, Path, Path, Path]:
    if account_id == "default":
        return (
            root / "var" / "trading-state.sqlite3",
            root / "apps" / "dashboard" / "data" / "summary.json",
            root / "var" / "strategy-state",
            root / "var" / "internal-paper-state.json",
            root / "var" / "worker.lock",
        )

    account_root = root / "var" / "accounts" / account_id
    return (
        account_root / "trading-state.sqlite3",
        root / "apps" / "dashboard" / "data" / "accounts" / f"{account_id}.json",
        account_root / "strategy-state",
        account_root / "internal-paper-state.json",
        account_root / "worker.lock",
    )


def env_file_candidates(root: Path) -> list[Path]:
    candidates = [root / ".env.paper.local"]
    if root.parent.name == ".worktrees":
        candidates.append(root.parent.parent / ".env.paper.local")
    return candidates


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
    account_id: str = "default"
    paper_only: bool = True

    @classmethod
    def from_env(
        cls, root: Path | None = None, account_id: str | None = None
    ) -> "RuntimeConfig":
        root_path = root or project_root()
        for env_path in env_file_candidates(root_path):
            apply_env_file(env_path)

        resolved_account_id = normalize_account_id(
            account_id or os.environ.get("NTS_ACCOUNT_ID")
        )
        (
            state_db_path,
            dashboard_summary_path,
            strategy_state_dir,
            internal_paper_state_path,
            worker_lock_path,
        ) = runtime_paths_for_account(root_path, resolved_account_id)
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
            default_broker=(
                resolve_account_env(
                    resolved_account_id,
                    scoped_key="BROKER",
                    fallback_key="NTS_DEFAULT_BROKER",
                    default="internal-paper",
                )
                or "internal-paper"
            ),
            alpaca_api_key=resolve_account_env(
                resolved_account_id,
                scoped_key="ALPACA_PAPER_API_KEY",
                fallback_key="ALPACA_PAPER_API_KEY",
            ),
            alpaca_api_secret=resolve_account_env(
                resolved_account_id,
                scoped_key="ALPACA_PAPER_API_SECRET",
                fallback_key="ALPACA_PAPER_API_SECRET",
            ),
            alpaca_trading_base_url=(
                resolve_account_env(
                    resolved_account_id,
                    scoped_key="ALPACA_PAPER_API_BASE_URL",
                    fallback_key="ALPACA_PAPER_API_BASE_URL",
                    default="https://paper-api.alpaca.markets/v2",
                )
                or "https://paper-api.alpaca.markets/v2"
            ),
            alpaca_data_base_url=(
                resolve_account_env(
                    resolved_account_id,
                    scoped_key="ALPACA_DATA_API_BASE_URL",
                    fallback_key="ALPACA_DATA_API_BASE_URL",
                    default="https://data.alpaca.markets",
                )
                or "https://data.alpaca.markets"
            ),
            account_id=resolved_account_id,
        )
