#!/bin/sh
cd `dirname $0`

# No PyInstaller: bleak/dbus-fast resolve cleanly as wheels on the target, and
# shipping source lets setup.sh build the venv on-device (where BlueZ lives).
mkdir -p dist

# Compatibility launcher at dist/main (the meta.json entrypoint): forward to the
# real venv launcher so a reload works whether the config points at dist/main
# or run.sh.
cat > dist/main <<'EOF'
#!/bin/sh
exec "`dirname $0`/../run.sh" "$@"
EOF
chmod +x dist/main

tar -czvf dist/archive.tar.gz \
    --exclude='__pycache__' \
    run.sh setup.sh requirements.txt meta.json src dist/main
