#!/bin/sh
set -eu
DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p "$DIR/module-cache"
/usr/bin/clang -fobjc-arc -O2 -Wall -Wextra -fmodules-cache-path="$DIR/module-cache" -framework AppKit -framework QuartzCore "$DIR/presenter.m" -o "$DIR/presenter"
file "$DIR/presenter"
shasum -a 256 "$DIR/presenter"
