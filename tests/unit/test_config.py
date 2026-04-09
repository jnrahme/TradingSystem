from __future__ import annotations

from new_trading_system.config import RuntimeConfig, env_file_candidates


def test_env_file_candidates_include_main_repo_when_running_in_worktree(
    tmp_path,
) -> None:
    repo_root = tmp_path / "NewTradingSystem"
    worktree_root = repo_root / ".worktrees" / "feature-a"
    worktree_root.mkdir(parents=True)

    candidates = env_file_candidates(worktree_root)

    assert candidates == [
        worktree_root / ".env.paper.local",
        repo_root / ".env.paper.local",
    ]


def test_runtime_config_loads_env_from_parent_repo_when_worktree_file_missing(
    tmp_path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "NewTradingSystem"
    worktree_root = repo_root / ".worktrees" / "feature-a"
    worktree_root.mkdir(parents=True)
    (repo_root / ".env.paper.local").write_text(
        "\n".join(
            [
                "ALPACA_PAPER_API_KEY=test-key",
                "ALPACA_PAPER_API_SECRET=test-secret",
                "NTS_DEFAULT_BROKER=alpaca-paper",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)
    monkeypatch.delenv("NTS_DEFAULT_BROKER", raising=False)

    config = RuntimeConfig.from_env(worktree_root)

    assert config.project_root == worktree_root
    assert config.alpaca_api_key == "test-key"
    assert config.alpaca_api_secret == "test-secret"
    assert config.default_broker == "alpaca-paper"
    assert config.state_db_path == worktree_root / "var" / "trading-state.sqlite3"
    assert (
        config.dashboard_summary_path
        == worktree_root / "apps" / "dashboard" / "data" / "summary.json"
    )


def test_runtime_config_supports_account_scoped_paths_and_credentials(
    tmp_path, monkeypatch
) -> None:
    repo_root = tmp_path / "NewTradingSystem"
    repo_root.mkdir(parents=True)
    (repo_root / ".env.paper.local").write_text(
        "\n".join(
            [
                "NTS_DEFAULT_BROKER=internal-paper",
                "ALPACA_PAPER_API_KEY=global-key",
                "ALPACA_PAPER_API_SECRET=global-secret",
                "NTS_ACCOUNT_SWING_TWO_BROKER=alpaca-paper",
                "NTS_ACCOUNT_SWING_TWO_ALPACA_PAPER_API_KEY=account-key",
                "NTS_ACCOUNT_SWING_TWO_ALPACA_PAPER_API_SECRET=account-secret",
            ]
        ),
        encoding="utf-8",
    )

    for key in [
        "NTS_ACCOUNT_ID",
        "NTS_DEFAULT_BROKER",
        "ALPACA_PAPER_API_KEY",
        "ALPACA_PAPER_API_SECRET",
        "NTS_ACCOUNT_SWING_TWO_BROKER",
        "NTS_ACCOUNT_SWING_TWO_ALPACA_PAPER_API_KEY",
        "NTS_ACCOUNT_SWING_TWO_ALPACA_PAPER_API_SECRET",
    ]:
        monkeypatch.delenv(key, raising=False)

    config = RuntimeConfig.from_env(repo_root, account_id="swing-two")

    assert config.account_id == "swing-two"
    assert config.default_broker == "alpaca-paper"
    assert config.alpaca_api_key == "account-key"
    assert config.alpaca_api_secret == "account-secret"
    assert (
        config.state_db_path
        == repo_root / "var" / "accounts" / "swing-two" / "trading-state.sqlite3"
    )
    assert (
        config.strategy_state_dir
        == repo_root / "var" / "accounts" / "swing-two" / "strategy-state"
    )
    assert (
        config.internal_paper_state_path
        == repo_root / "var" / "accounts" / "swing-two" / "internal-paper-state.json"
    )
    assert (
        config.worker_lock_path
        == repo_root / "var" / "accounts" / "swing-two" / "worker.lock"
    )
    assert (
        config.dashboard_summary_path
        == repo_root / "apps" / "dashboard" / "data" / "accounts" / "swing-two.json"
    )
