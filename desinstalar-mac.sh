#!/bin/sh
# Desfaz o instalar-mac.sh. Listas, favoritos e o resto dos seus dados ficam onde estão.
set -u

ROOT=$(cd "$(dirname "$0")" && pwd -P)
DOMAIN="gui/$(id -u)"
AGENTS="$HOME/Library/LaunchAgents"

for LABEL in local.sofa.barra local.sofa.vigia; do
    launchctl bootout "$DOMAIN/$LABEL" 2> /dev/null
    rm -f "$AGENTS/$LABEL.plist"
done
rm -rf "$HOME/Applications/Sofá.app"
rm -f "$ROOT/cache/vigia-desligado"
echo "Pronto: o Sofá não liga mais sozinho. Para usar à mão: python3 server.py"
