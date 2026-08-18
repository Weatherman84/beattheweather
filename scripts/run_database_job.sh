#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: run_database_job.sh COMMIT_MESSAGE COMMAND [ARGS...] [--then COMMAND ...]" >&2
  exit 2
fi

commit_message="$1"
shift
job_arguments=("$@")
maximum_attempts=3
database_path="data/weatherman.db"
history_archive_path="data/history_archive"
collection_report_path="data/collection"
database_maintenance_threshold_bytes=$((35 * 1024 * 1024))
database_size_limit_bytes=$((48 * 1024 * 1024))
fast_database_job="${WEATHERMAN_FAST_DATABASE_JOB:-0}"

run_job() {
  local segment=()
  local token
  for token in "${job_arguments[@]}"; do
    if [[ "$token" == "--then" ]]; then
      if [[ ${#segment[@]} -eq 0 ]]; then
        echo "empty command before --then" >&2
        exit 2
      fi
      env PYTHONPATH=src "${segment[@]}"
      segment=()
    else
      segment+=("$token")
    fi
  done
  if [[ ${#segment[@]} -eq 0 ]]; then
    echo "empty final database command" >&2
    exit 2
  fi
  env PYTHONPATH=src "${segment[@]}"
}

git config user.name github-actions[bot]
git config user.email 41898282+github-actions[bot]@users.noreply.github.com

for ((attempt = 1; attempt <= maximum_attempts; attempt++)); do
  if [[ $attempt -gt 1 ]]; then
    echo "Remote main changed; rerunning the collector on the newest database (attempt $attempt)."
    git fetch origin main
    git switch -C main origin/main
    python -m pip install -r requirements.txt
  fi

  run_job
  if [[ "$fast_database_job" == "1" ]]; then
    env PYTHONPATH=src python -m weatherman.cli audit-coverage --fast
  else
    env PYTHONPATH=src python -m weatherman.cli maintain-database --retention-days 3
    env PYTHONPATH=src python -m weatherman.cli audit-coverage
  fi
  database_size_bytes=$(wc -c < "$database_path")
  if [[ "$fast_database_job" == "1" ]] && ((database_size_bytes >= database_maintenance_threshold_bytes)); then
    echo "Fast collector reached the 35-MiB maintenance threshold; running verified retention now."
    env PYTHONPATH=src python -m weatherman.cli maintain-database --retention-days 3
    env PYTHONPATH=src python -m weatherman.cli audit-coverage
    database_size_bytes=$(wc -c < "$database_path")
  fi
  if ((database_size_bytes >= database_size_limit_bytes)); then
    echo "Database is still too large after maintenance: ${database_size_bytes} bytes." >&2
    echo "Refusing to persist a database outside the Stage-1 operating band." >&2
    exit 1
  fi
  oversized_archive=$(find "$history_archive_path" -type f -size +95M -print -quit 2>/dev/null || true)
  if [[ -n "$oversized_archive" ]]; then
    echo "History archive file exceeds the 95-MiB safety limit: $oversized_archive" >&2
    exit 1
  fi
  git add -f "$database_path"
  if [[ "$fast_database_job" != "1" ]] && [[ -d "$history_archive_path" ]]; then
    git add -f "$history_archive_path"
  fi
  if [[ -d "$collection_report_path" ]]; then
    git add -f "$collection_report_path"
  fi
  if git diff --cached --quiet; then
    echo "Database collector produced no new snapshot."
    exit 0
  fi
  git commit -m "$commit_message"
  git restore --worktree -- .
  if git push origin HEAD:main; then
    exit 0
  fi
  git fetch origin main
  if git merge-base --is-ancestor origin/main HEAD; then
    echo "Database push failed, but remote main did not advance." >&2
    echo "This is not a race; refusing to rerun the collector." >&2
    exit 1
  fi
  if [[ $attempt -eq maximum_attempts ]]; then
    echo "Database push still raced after $maximum_attempts attempts." >&2
    exit 1
  fi
done
