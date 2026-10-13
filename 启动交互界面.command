#!/bin/zsh
set -eu

ATOMMOVR_UI_DIR="${0:A:h}"
exec /bin/bash "$ATOMMOVR_UI_DIR/start.sh" "$@"
