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
database_size_limit_bytes=$((95 * 1024 * 1024))

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
  env PYTHONPATH=src python -m weatherman.cli maintain-database --hourly-days 7
  database_size_bytes=$(wc -c < "$database_path")
  if ((database_size_bytes >= database_size_limit_bytes)); then
    echo "Database is still too large after maintenance: ${database_size_bytes} bytes." >&2
    echo "Refusing to create an unpushable commit; GitHub's hard limit is 100 MiB." >&2
    exit 1
  fi
  git add -f "$database_path"
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
