#!/usr/bin/env zsh

set -euo pipefail

ROOT="/Users/humdaan/repos/GR86_OS/sandbox"
export MPLBACKEND=Agg
export MPLCONFIGDIR="$ROOT/.mplconfig"
export XDG_CACHE_HOME="$ROOT/.cache"

mkdir -p "$MPLCONFIGDIR" "$XDG_CACHE_HOME"
source "$ROOT/.venv/bin/activate"

echo "Offline sandbox environment ready."
echo "Usage: source /Users/humdaan/repos/GR86_OS/sandbox/offline_env.sh"
echo "Python: $(python --version 2>&1)"
echo "Packages:"
python - <<'PY'
import matplotlib
import numpy
import scipy
print(f"  numpy {numpy.__version__}")
print(f"  scipy {scipy.__version__}")
print(f"  matplotlib {matplotlib.__version__}")
PY

echo
echo "Examples:"
echo "  python cabin_noise_simulation.py"
echo "  jupyter lab"
