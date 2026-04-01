#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="${SOURCE_DIR:-$HOME/apps/voice-hub}"
TARGET_DIR="${TARGET_DIR:-/opt/ideatect}"
SERVICE_NAME="${SERVICE_NAME:-ideatect-chat.service}"

if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  echo "Source repo not found at $SOURCE_DIR" >&2
  exit 1
fi

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Target directory not found at $TARGET_DIR" >&2
  exit 1
fi

echo "Deploying from $SOURCE_DIR to $TARGET_DIR"

sudo rsync -av \
  --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  "$SOURCE_DIR"/ "$TARGET_DIR"/

if [[ -x "$TARGET_DIR/.venv/bin/pip" && -f "$TARGET_DIR/requirements.txt" ]]; then
  sudo "$TARGET_DIR/.venv/bin/pip" install -r "$TARGET_DIR/requirements.txt"
fi

sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager

echo "Deployment complete."
