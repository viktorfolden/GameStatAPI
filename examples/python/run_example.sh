#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"

if [[ $# -eq 0 ]]; then
  set -- login
fi
case "$1" in
  login|signup|submit) ;;
  -h|--help)
    echo "Usage: $0 [login|signup|submit] [options] (default: login)"
    echo "Submit options: --run-id UUID --score N --hits N --misses N --enemies-killed N --play-time-seconds N"
    echo "Creates .venv if needed and installs the example's dependencies."
    echo "Override SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, or GAME_API_URL via environment variables."
    exit 0
    ;;
  *)
    echo "Usage: $0 [login|signup|submit] [options]" >&2
    exit 2
    ;;
esac
export SUPABASE_URL="${SUPABASE_URL:-https://sghwafwnxfqcbdpiabnq.supabase.co}"
export SUPABASE_PUBLISHABLE_KEY="${SUPABASE_PUBLISHABLE_KEY:-sb_publishable_4mmrRASle-Xv8l1-qJqQJA_srF6z1i4}"
export GAME_API_URL="${GAME_API_URL:-https://viktor-game-api.onrender.com}"

if [[ ! -x "$PYTHON" ]]; then
  python3 -m venv "$PROJECT_DIR/.venv"
fi
"$PYTHON" -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
exec "$PYTHON" "$SCRIPT_DIR/game_client.py" "$@"
