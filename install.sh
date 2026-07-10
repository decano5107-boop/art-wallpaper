#!/usr/bin/env bash
#
# Instalador del rotador de fondo de escritorio (arte icónico + ficha técnica).
# Deja un LaunchAgent que cambia el wallpaper cada 30 minutos.
#
#   ./install.sh            instala y arranca
#   ./install.sh --uninstall  desinstala (para y borra el LaunchAgent)
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/rotate.py"
LABEL="com.art-wallpaper.rotator"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
TEMPLATE="$HERE/com.art-wallpaper.rotator.plist.template"
ART_HOME="$HOME/.art-wallpaper"
LOG="$ART_HOME/rotator.log"

info()  { printf "\033[1;36m▸\033[0m %s\n" "$1"; }
ok()    { printf "\033[1;32m✓\033[0m %s\n" "$1"; }
warn()  { printf "\033[1;33m!\033[0m %s\n" "$1"; }

uninstall() {
  info "Desinstalando..."
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  ok "LaunchAgent eliminado. (Se conservan la caché y el catálogo; borra $ART_HOME si quieres limpiar todo.)"
  exit 0
}

[[ "${1:-}" == "--uninstall" ]] && uninstall

# --- 1. Este instalador es solo para macOS ---
if [[ "$(uname)" != "Darwin" ]]; then
  warn "Este instalador usa launchd y osascript: solo funciona en macOS."
  exit 1
fi

# --- 2. Entorno de Python aislado (venv propio) ---
# Usamos un venv dedicado en $ART_HOME/venv en vez del python del sistema o de un venv activo.
# Motivos: (a) el LaunchAgent necesita una ruta ESTABLE (un venv activo hoy puede no existir
# mañana); (b) evita el PEP 668 de Homebrew ("externally-managed-environment") y el error de
# "pip install --user" dentro de un venv. El venv se crea con un python3 base estable.
VENV="$ART_HOME/venv"
PYTHON="$VENV/bin/python3"
mkdir -p "$ART_HOME"

if [[ ! -x "$PYTHON" ]]; then
  info "Creando entorno aislado en ${VENV}..."
  BASE_PY=""
  # Preferimos intérpretes estables por ruta (NO el del venv activo) para crear el venv.
  for cand in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1; then BASE_PY="$(command -v "$cand")"; break; fi
  done
  [[ -z "$BASE_PY" ]] && { warn "No encontré python3. Instala Xcode Command Line Tools:  xcode-select --install"; exit 1; }
  "$BASE_PY" -m venv "$VENV" || { warn "No pude crear el venv con $BASE_PY."; exit 1; }
fi

if ! "$PYTHON" -c "import PIL" >/dev/null 2>&1; then
  info "Instalando Pillow en el venv..."
  "$PYTHON" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  "$PYTHON" -m pip install --quiet pillow || {
    warn "No pude instalar Pillow. Prueba:  $PYTHON -m pip install pillow"; exit 1; }
fi
ok "python3 (venv): $PYTHON  (Pillow OK)"

# --- 3. Directorios de trabajo ---
mkdir -p "$ART_HOME/cache" "$ART_HOME/current" "$HOME/Library/LaunchAgents"

# --- 4. Generar el plist desde la plantilla ---
info "Generando LaunchAgent..."
sed -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__SCRIPT__|$SCRIPT|g" \
    -e "s|__WORKDIR__|$HERE|g" \
    -e "s|__LOG__|$LOG|g" \
    "$TEMPLATE" > "$PLIST"

# --- 5. (Re)cargar el LaunchAgent ---
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
if launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null; then :; else launchctl load -w "$PLIST"; fi
ok "LaunchAgent cargado ($LABEL) — rotación cada 30 min."

# --- 6. Primera rotación ya mismo (para ver algo enseguida) ---
info "Aplicando el primer fondo..."
if "$PYTHON" "$SCRIPT" --once; then
  ok "¡Listo! Tu escritorio ya debería mostrar una obra con su ficha técnica."
else
  warn "La primera rotación falló (¿sin red?). launchd reintentará en 30 min. Log: $LOG"
fi

cat <<EOF

  Comandos útiles:
    $PYTHON $SCRIPT --once            # cambiar de obra ahora
    $PYTHON $SCRIPT --id nighthawks   # forzar una obra
    tail -f "$LOG"                    # ver el log
    "$HERE/install.sh" --uninstall    # quitar la rotación

EOF
