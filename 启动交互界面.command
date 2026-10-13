#!/bin/zsh
set -eu

ATOMMOVR_UI_DIR="${0:A:h}"
ATOMMOVR_UPSTREAM_REF="cca2553985bb9d81b19cae9b83074df4816502f9"
ATOMMOVR_SOURCE_DIR="${ATOMMOVR_SOURCE:-}"

if [[ -z "$ATOMMOVR_SOURCE_DIR" && -d "$ATOMMOVR_UI_DIR/.deps/atommovr/atommovr" ]]; then
  ATOMMOVR_SOURCE_DIR="$ATOMMOVR_UI_DIR/.deps/atommovr"
elif [[ -z "$ATOMMOVR_SOURCE_DIR" && -d "$HOME/Downloads/atommovr-main/atommovr" ]]; then
  ATOMMOVR_SOURCE_DIR="$HOME/Downloads/atommovr-main"
fi

if [[ -z "$ATOMMOVR_SOURCE_DIR" ]]; then
  if ! command -v git >/dev/null 2>&1; then
    print "首次安装需要 Git。请先安装 Git 后重试。"
    read -k 1 "?按任意键退出。"
    exit 1
  fi
  mkdir -p "$ATOMMOVR_UI_DIR/.deps"
  git clone https://github.com/bernienlab/atommovr.git "$ATOMMOVR_UI_DIR/.deps/atommovr"
  git -C "$ATOMMOVR_UI_DIR/.deps/atommovr" checkout "$ATOMMOVR_UPSTREAM_REF"
  ATOMMOVR_SOURCE_DIR="$ATOMMOVR_UI_DIR/.deps/atommovr"
fi

if [[ ! -d "$ATOMMOVR_SOURCE_DIR/atommovr" ]]; then
  print "未找到完整的 atommovr 源码：$ATOMMOVR_SOURCE_DIR"
  print "可将 ATOMMOVR_SOURCE 设置为官方源码目录后重试。"
  read -k 1 "?按任意键退出。"
  exit 1
fi

if [[ -x "$ATOMMOVR_SOURCE_DIR/.venv/bin/python" ]]; then
  ATOMMOVR_PYTHON="$ATOMMOVR_SOURCE_DIR/.venv/bin/python"
else
  ATOMMOVR_PYTHON="$ATOMMOVR_UI_DIR/.venv/bin/python"
  if [[ ! -x "$ATOMMOVR_PYTHON" ]]; then
    if ! command -v python3 >/dev/null 2>&1; then
      print "需要 Python 3.11 或更高版本。"
      read -k 1 "?按任意键退出。"
      exit 1
    fi
    python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
      print "需要 Python 3.11 或更高版本。"
      read -k 1 "?按任意键退出。"
      exit 1
    }
    python3 -m venv "$ATOMMOVR_UI_DIR/.venv"
  fi
fi

mkdir -p "$ATOMMOVR_UI_DIR/.runtime"
DEPENDENCY_MARKER="$ATOMMOVR_UI_DIR/.runtime/dependencies-v1.0.0"
if [[ ! -f "$DEPENDENCY_MARKER" ]]; then
  "$ATOMMOVR_PYTHON" -m pip install -r "$ATOMMOVR_UI_DIR/requirements.txt"
  "$ATOMMOVR_PYTHON" -m pip install -e "$ATOMMOVR_SOURCE_DIR"
  touch "$DEPENDENCY_MARKER"
fi

cd "$ATOMMOVR_UI_DIR"
export ATOMMOVR_SOURCE="$ATOMMOVR_SOURCE_DIR"
export ATOMMOVR_UI_STATE_DIR="$ATOMMOVR_UI_DIR/.runtime"
export GRADIO_ANALYTICS_ENABLED=False
export MPLBACKEND=Agg
exec "$ATOMMOVR_PYTHON" "$ATOMMOVR_UI_DIR/app.py"
