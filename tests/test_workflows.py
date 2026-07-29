from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_database_workflows_clean_generated_changes_before_rebase() -> None:
    """A rebase must not be blocked by metadata refreshed during installation."""
    for filename in ("new-trading-airports-backfill.yml", "live-decisions.yml"):
        workflow = (ROOT / ".github" / "workflows" / filename).read_text()
        commit_at = workflow.index("git diff --cached --quiet || git commit")
        restore_at = workflow.index("git restore --worktree -- .")
        pull_at = workflow.index("git pull --rebase")

        assert commit_at < restore_at < pull_at


def test_live_workflow_runs_parallel_shadow_checks_every_ten_minutes() -> None:
    workflow = (ROOT / ".github" / "workflows" / "live-decisions.yml").read_text()
    assert 'cron: "*/10 * * * *"' in workflow
    assert "Parallel shadow watcher" in workflow
