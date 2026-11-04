#!/bin/sh
# Deixa o Sofá sempre ligado no Mac: registra o vigia e o ícone da barra no login. Rodar uma vez: sh instalar-mac.sh
set -eu

fail() {
    echo "$1" >&2
    exit 1
}

[ "$(uname)" = "Darwin" ] || fail "Este instalador é só para o Mac. Nos outros sistemas, use: python3 server.py"

ROOT=$(cd "$(dirname "$0")" && pwd -P)
REAL_HOME=$(cd "$HOME" && pwd -P)
case "$ROOT/" in
    "$REAL_HOME/Desktop/"* | "$REAL_HOME/Documents/"* | "$REAL_HOME/Downloads/"*)
        fail "O macOS não deixa programas em segundo plano lerem Mesa, Documentos e Downloads: mova a pasta do projeto para outro lugar (por exemplo $HOME/iptv) e rode de novo." ;;
esac

PY=$(command -v python3) || fail "Falta o Python 3. Veja \"Do que você precisa\" no README."
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail "O Sofá precisa do Python 3.9 ou mais novo."
command -v swiftc > /dev/null || fail "Falta o compilador da Apple. Rode: xcode-select --install"

cd "$ROOT"
BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
echo "Compilando o app do Mac..."
swiftc -O -o "$BUILD/Sofa" -framework AppKit -framework WebKit mac/Sofa.swift

DOMAIN="gui/$(id -u)"
AGENTS="$HOME/Library/LaunchAgents"
APP="$HOME/Applications/Sofá.app"
LABELS="local.sofa.vigia local.sofa.barra"

for LABEL in $LABELS; do
    launchctl bootout "$DOMAIN/$LABEL" 2> /dev/null || true
done

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$AGENTS"
cp "$BUILD/Sofa" "$APP/Contents/MacOS/Sofa"
cp mac/Info.plist "$APP/Contents/Info.plist"
codesign -s - --force "$APP" 2> /dev/null

"$PY" vigia_system.py vigia-plist "$PY" > "$AGENTS/local.sofa.vigia.plist"
"$PY" vigia_system.py app-plist "$APP/Contents/MacOS/Sofa" > "$AGENTS/local.sofa.barra.plist"

for LABEL in $LABELS; do
    # Logo depois do bootout, o macOS às vezes ainda recusa o mesmo nome
    for TRY in 1 2 3 4 5; do
        launchctl bootstrap "$DOMAIN" "$AGENTS/$LABEL.plist" 2> /dev/null && break
        [ "$TRY" -lt 5 ] || fail "O macOS não aceitou $LABEL. Veja Ajustes do Sistema > Geral > Itens de Início."
        sleep 1
    done
done

STATUS=""
for TRY in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    STATUS=$(curl -fsS --max-time 2 http://127.0.0.1:8010/api/status 2> /dev/null) || STATUS=""
    case "$STATUS" in
        "" | *'"title": "Sofá ligando"'*) sleep 1 ;;
        *) break ;;
    esac
done
[ -n "$STATUS" ] || fail "O vigia não respondeu. Veja o que ele escreveu em $ROOT/vigia.log"

printf '%s' "$STATUS" | "$PY" -c '
import json, sys
status = json.load(sys.stdin)
address = status["address"]
print(status["title"])
print("Endereço para a TV:", f"http://{address['"'"'ip'"'"']}:{address['"'"'port'"'"']}" if address["ip"] else "sem rede no Mac")
if address["name"]:
    print("No tablet:", f"http://{address['"'"'name'"'"']}:{address['"'"'status_port'"'"']}")
'
