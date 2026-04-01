#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/apps/voice-hub}"
BRANCH="${BRANCH:-main}"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "Repo not found at $REPO_DIR" >&2
  exit 1
fi

cd "$REPO_DIR"

echo "Updating repository in $REPO_DIR"
git fetch --all --prune
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "Update complete."
