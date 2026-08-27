#!/bin/sh
cd `dirname $0`

# Build the venv on first run (idempotent - guards on .installed).
if [ ! -f .installed ]; then
    ./setup.sh || exit 1
fi

# Run from src/ so `from models...`/`import profoto...` resolve. Forward "$@"
# so viam-server's socket-path argument reaches the module.
exec venv/bin/python src/main.py "$@"
