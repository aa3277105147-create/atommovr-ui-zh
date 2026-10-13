#!/usr/bin/env bash
set -eu

ATOMMOVR_UI_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ATOMMOVR_VERSION_CHECK='import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'

if [[ -n "${ATOMMOVR_PYTHON:-}" ]]; then
  if "$ATOMMOVR_PYTHON" -c "$ATOMMOVR_VERSION_CHECK" >/dev/null 2>&1; then
    exec "$ATOMMOVR_PYTHON" "$ATOMMOVR_UI_DIR/launch.py" "$@"
  fi
  printf '%s\n' 'ATOMMOVR_PYTHON 必须指向可运行的 Python 3.11+ 解释器。' >&2
  exit 1
fi

for ATOMMOVR_CANDIDATE in \
  "$ATOMMOVR_UI_DIR/.venv/bin/python" \
  "${ATOMMOVR_SOURCE:-}/.venv/bin/python" \
  "$HOME/Downloads/atommovr-main/.venv/bin/python" \
  "$ATOMMOVR_UI_DIR/.deps/atommovr/.venv/bin/python" \
  python3.12 python3.11 python3.13 python3.14 python3 python; do
  if "$ATOMMOVR_CANDIDATE" -c "$ATOMMOVR_VERSION_CHECK" >/dev/null 2>&1; then
    exec "$ATOMMOVR_CANDIDATE" "$ATOMMOVR_UI_DIR/launch.py" "$@"
  fi
done

printf '%s\n' '需要 Python 3.11 或更高版本；安装后重试，或设置 ATOMMOVR_PYTHON。' >&2
exit 1
