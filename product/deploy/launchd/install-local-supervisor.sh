#!/bin/sh
# Install the sole local TrainLab scheduler.  This is intentionally a user
# LaunchAgent: no administrator privilege, shell wrapper or lower-layer timer is involved.
set -eu

label="com.trainlab.orchestrator-supervisor"
replace="false"
start="true"
for argument in "$@"; do
  case "$argument" in
    --replace) replace="true" ;;
    --no-start) start="false" ;;
    *) echo "usage: $0 [--replace] [--no-start]" >&2; exit 64 ;;
  esac
done

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
template="$script_dir/$label.plist.template"
launch_agents="$HOME/Library/LaunchAgents"
target="$launch_agents/$label.plist"
launch_working_directory="$HOME/Library/Application Support/TrainLab"
launch_log_directory="$HOME/Library/Logs/TrainLab"
uid=$(id -u)

[ -x "$project_root/.venv/bin/python" ] || { echo "missing project virtual environment" >&2; exit 65; }
[ -f "$template" ] || { echo "missing launchd template" >&2; exit 65; }
python_link="$project_root/.venv/bin/python"
real_python=$(PYTHONPATH= "$python_link" -c 'from pathlib import Path; import sys; print(Path(sys.executable).resolve(strict=True))')
case "$real_python" in
  /*) ;;
  *) echo "resolved Python is not absolute" >&2; exit 65 ;;
esac
case "$real_python" in
  /Volumes/*) echo "resolved Python cannot be launched from an external volume" >&2; exit 65 ;;
esac
[ -f "$real_python" ] && [ -x "$real_python" ] && [ ! -L "$real_python" ] || { echo "resolved Python is not a regular executable" >&2; exit 65; }
runtime_path=$(PYTHONPATH="$project_root/src" "$project_root/.venv/bin/python" -c 'from trainlab.runtime_environment import bounded_runtime_path; print(bounded_runtime_path())')
[ -n "$runtime_path" ] || { echo "no usable runtime PATH" >&2; exit 65; }
mkdir -p "$launch_working_directory" "$launch_log_directory"
chmod 700 "$launch_working_directory" "$launch_log_directory"
stdout_log="$launch_log_directory/supervisor.launchd.out.log"
stderr_log="$launch_log_directory/supervisor.launchd.err.log"
touch "$stdout_log" "$stderr_log"
chmod 600 "$stdout_log" "$stderr_log"
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
escaped_python=$(printf '%s' "$real_python" | sed 's/[\\&|]/\\&/g')
escaped_working_directory=$(printf '%s' "$launch_working_directory" | sed 's/[\\&|]/\\&/g')
escaped_log_directory=$(printf '%s' "$launch_log_directory" | sed 's/[\\&|]/\\&/g')
sed -e "s|@PROJECT_ROOT@|$escaped_root|g" -e "s|@RUNTIME_PATH@|$escaped_path|g" -e "s|@PYTHON_EXECUTABLE@|$escaped_python|g" -e "s|@LAUNCH_WORKING_DIRECTORY@|$escaped_working_directory|g" -e "s|@LAUNCH_LOG_DIRECTORY@|$escaped_log_directory|g" "$template" > "$temporary"
plutil -lint "$temporary" >/dev/null
chmod 600 "$temporary"

if [ "$replace" = "true" ]; then
  launchctl bootout "gui/$uid/$label" 2>/dev/null || true
fi
mv -f "$temporary" "$target"
trap - EXIT HUP INT TERM
if [ "$start" != "true" ]; then
  echo "installed $label without loading; review and bootstrap explicitly"
  exit 0
fi
launchctl bootstrap "gui/$uid" "$target"
launchctl kickstart -k "gui/$uid/$label"
echo "installed $label"
