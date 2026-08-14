from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_database_workflows_use_latest_main_and_sqlite_safe_retry_helper() -> None:
    filenames = (
        "collect.yml",
        "initial-backfill.yml",
        "live-decisions.yml",
        "maintenance.yml",
        "market-history-backfill.yml",
        "new-trading-airports-backfill.yml",
        "research.yml",
        "stage1-recovery.yml",
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
    assert "reconcile_fixed_checkpoints" not in helper
    assert "maintain-database --retention-days 3" in helper
    assert "audit-coverage" in helper
    assert 'history_archive_path="data/history_archive"' in helper
    assert 'git add -f "$history_archive_path"' in helper
    assert "database_size_limit_bytes" in helper
    assert "git push origin HEAD:main" in helper
    assert "git merge-base --is-ancestor origin/main HEAD" in helper
    assert "This is not a race; refusing to rerun the collector." in helper
    assert "git pull" not in helper


def test_live_workflow_runs_consolidated_collector_every_ten_minutes() -> None:
    workflow = (ROOT / ".github" / "workflows" / "live-decisions.yml").read_text()
    assert 'cron: "*/10 * * * *"' in workflow
    assert "Consolidated ten-minute collector" in workflow
    assert "run-collector" in workflow
    assert "WEATHERMAN_SCHEDULED_AT" in workflow
    assert 'WEATHERMAN_FAST_DATABASE_JOB: "1"' in workflow


def test_full_archive_maintenance_is_daily_not_part_of_every_fast_poll() -> None:
    workflow = (ROOT / ".github" / "workflows" / "maintenance.yml").read_text()
    helper = (ROOT / "scripts" / "run_database_job.sh").read_text()
    assert 'cron: "17 2 * * *"' in workflow
    assert "scripts/run_database_job.sh" in workflow
    assert "fast_database_job" in helper
    assert "audit-coverage --fast" in helper
    assert 'if [[ "$fast_database_job" != "1" ]]' in helper


def test_research_schedule_does_not_compete_with_ten_minute_database_writer() -> None:
    workflow = (ROOT / ".github" / "workflows" / "research.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
