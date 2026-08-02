from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_database_workflows_use_latest_main_and_sqlite_safe_retry_helper() -> None:
    filenames = (
        "collect.yml",
        "initial-backfill.yml",
        "live-decisions.yml",
        "market-history-backfill.yml",
        "new-trading-airports-backfill.yml",
        "research.yml",
    )
    for filename in filenames:
        workflow = (ROOT / ".github" / "workflows" / filename).read_text()
        assert "group: weatherman-database" in workflow
        assert "ref: main" in workflow
        assert "fetch-depth: 0" in workflow
        assert "scripts/run_database_job.sh" in workflow
        assert "git pull --rebase" not in workflow
        assert "pip install ." not in workflow


def test_database_retry_helper_reruns_instead_of_merging_sqlite() -> None:
    helper = (ROOT / "scripts" / "run_database_job.sh").read_text()
    assert "maximum_attempts=3" in helper
    assert "git fetch origin main" in helper
    assert "git switch -C main origin/main" in helper
    assert "run_job" in helper
    assert "git push origin HEAD:main" in helper
    assert "git pull" not in helper


def test_live_workflow_runs_parallel_shadow_checks_every_ten_minutes() -> None:
    workflow = (ROOT / ".github" / "workflows" / "live-decisions.yml").read_text()
    assert 'cron: "*/10 * * * *"' in workflow
    assert "Parallel shadow watcher" in workflow
