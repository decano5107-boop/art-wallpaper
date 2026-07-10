#!/usr/bin/env bash
#
# Convierte esta carpeta en un repositorio git independiente (proyecto personal).
# Uso:  ./init-repo.sh
# Luego crea un repo vacío en GitHub y sigue las instrucciones que imprime al final.
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [ -d .git ]; then
  echo "Ya es un repo git. Nada que hacer."
  exit 0
fi

git init -q
git add .gitignore README.md CLAUDE.md ROADMAP.md CHANGELOG.md LICENSE \
        rotate.py artworks.json install.sh init-repo.sh \
        com.art-wallpaper.rotator.plist.template
git commit -q -m "Art Wallpaper: initial commit"
git branch -M main

cat <<'EOF'

Repo local creado (rama main).

Ahora, para subirlo a GitHub:
  1. Crea un repo VACIO en https://github.com/new  (p. ej. "art-wallpaper", privado, sin README).
  2. Conéctalo y sube:
       git remote add origin https://github.com/<tu-usuario>/art-wallpaper.git
       git push -u origin main

A partir de ahí, para iterar:
  - edita, prueba con:  ~/.art-wallpaper/venv/bin/python3 rotate.py --selftest
  - git add -p && git commit -m "..."  && git push
EOF
