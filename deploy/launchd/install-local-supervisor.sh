#!/bin/sh
# Install the sole local TrainLab scheduler.  This is intentionally a user
# LaunchAgent: no administrator privilege, shell wrapper or lower-layer timer is involved.
set -eu

label="com.trainlab.orchestrator-supervisor"
replace="false"
if [ "${1:-}" = "--replace" ]; then
  replace="true"
elif [ "$#" -ne 0 ]; then
  echo "usage: $0 [--replace]" >&2
  exit 64
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
template="$script_dir/$label.plist.template"
launch_agents="$HOME/Library/LaunchAgents"
target="$launch_agents/$label.plist"
uid=$(id -u)

[ -x "$project_root/.venv/bin/trainlab" ] || { echo "missing project virtual environment" >&2; exit 65; }
[ -f "$template" ] || { echo "missing launchd template" >&2; exit 65; }
runtime_path=$(PYTHONPATH="$project_root/src" "$project_root/.venv/bin/python" -c 'from trainlab.runtime_environment import bounded_runtime_path; print(bounded_runtime_path())')
[ -n "$runtime_path" ] || { echo "no usable runtime PATH" >&2; exit 65; }
mkdir -p "$project_root/logs"
chmod 700 "$project_root/logs"
mkdir -p "$launch_agents"
chmod 700 "$launch_agents"

if [ -e "$target" ] && [ "$replace" != "true" ]; then
  echo "LaunchAgent already exists; rerun with --replace after review" >&2
  exit 73
fi
if [ -L "$target" ]; then
  echo "refusing symbolic-link LaunchAgent target" >&2
  exit 73
fi

umask 077
temporary=$(mktemp "$launch_agents/.${label}.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM
escaped_root=$(printf '%s' "$project_root" | sed 's/[\\&|]/\\&/g')
escaped_path=$(printf '%s' "$runtime_path" | sed 's/[\\&|]/\\&/g')
sed -e "s|@PROJECT_ROOT@|$escaped_root|g" -e "s|@RUNTIME_PATH@|$escaped_path|g" "$template" > "$temporary"
plutil -lint "$temporary" >/dev/null
chmod 600 "$temporary"

if [ "$replace" = "true" ]; then
  launchctl bootout "gui/$uid/$label" 2>/dev/null || true
fi
mv -f "$temporary" "$target"
trap - EXIT HUP INT TERM
launchctl bootstrap "gui/$uid" "$target"
launchctl kickstart -k "gui/$uid/$label"
echo "installed $label"
