#!/bin/sh
# Käynnistää Opintolainalaskurin Linuxissa.
exec python3 "$(dirname "$0")/opintolainalaskuri.py" "$@"
