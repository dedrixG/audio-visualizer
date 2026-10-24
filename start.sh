#!/usr/bin/env bash
# Double-click / menu launcher for the audio visualizer.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$ROOT"
PORT="${PORT:-8765}"
BIND="${BIND:-127.0.0.1}"

install_launcher() {
  local apps="$HOME/.local/share/applications"
  mkdir -p "$apps" "$HOME/.local/share/icons/hicolor/scalable/apps"
  cp -f "$ROOT/share/icon.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/audio-visualizer.svg"
  sed "s|@ROOT@|$ROOT|g" "$ROOT/share/audio-visualizer.desktop" > "$apps/audio-visualizer.desktop"
  chmod +x "$apps/audio-visualizer.desktop"
}

install_launcher || true

case "$BIND" in
  127.0.0.1|localhost|::1) ;;
  *)
    if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
      if ! firewall-cmd --quiet --query-port="${PORT}/tcp" 2>/dev/null; then
        echo "Note: Fedora firewall is not allowing TCP ${PORT}."
        echo "The phone on Wi-Fi needs that port. Tailscale often still works."
        echo "Anyone on that network who opens the URL can hear playback."
        echo "  sudo firewall-cmd --add-port=${PORT}/tcp"
        echo "  sudo firewall-cmd --add-port=${PORT}/tcp --permanent"
        echo
      fi
    fi
    ;;
esac

exec python3 "$ROOT/server.py" --port "$PORT" --bind "$BIND" --open
