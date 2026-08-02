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
  git add -f data/weatherman.db
  if git diff --cached --quiet; then
    echo "Database collector produced no new snapshot."
    exit 0
  fi
  git commit -m "$commit_message"
  git restore --worktree -- .
  if git push origin HEAD:main; then
    exit 0
  fi
  if [[ $attempt -eq maximum_attempts ]]; then
    echo "Database push still raced after $maximum_attempts attempts." >&2
    exit 1
  fi
done
