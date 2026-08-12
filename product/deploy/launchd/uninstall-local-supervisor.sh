#!/bin/sh
# Stop and remove only the TrainLab user LaunchAgent; logs and data stay intact.
set -eu

label="com.trainlab.orchestrator-supervisor"
target="$HOME/Library/LaunchAgents/$label.plist"
uid=$(id -u)
launchctl bootout "gui/$uid/$label" 2>/dev/null || true
if [ -L "$target" ]; then
  echo "refusing symbolic-link LaunchAgent target" >&2
  exit 73
fi
if [ -e "$target" ]; then
  [ -f "$target" ] || { echo "refusing non-regular LaunchAgent target" >&2; exit 73; }
  rm -f "$target"
fi
echo "removed $label; logs and TrainLab data were retained"
