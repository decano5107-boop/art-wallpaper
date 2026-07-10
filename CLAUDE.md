# CLAUDE.md — Art Wallpaper

> Manual de operación + memoria del proyecto. Si eres una sesión de Claude que aterriza aquí en
> frío, lee esto de arriba a abajo y estarás productivo en ~3 minutos. Dueño: **Diego Cano**.

## Qué es

Utilidad **personal** para macOS que cambia el fondo de escritorio cada 30 min por una **pintura
icónica** a resolución original, montada como en una **galería de museo** (pared cálida con luz de
foco, marco dorado, sombra) y acompañada de una **cartela** con: nombre · autor (con foto) · año ·
país (con bandera) · museo · ciudad · y una **nota de por qué la obra es célebre**.

> ⚠️ **Es un proyecto 100% personal y de gusto por el arte.** No tiene ninguna relación con
> trabajo, clientes ni otros repos. No lo mezcles con nada más.

## Arranque rápido

```bash
./install.sh                                   # crea venv + LaunchAgent (cada 30 min) + primer fondo
~/.art-wallpaper/venv/bin/python3 rotate.py --once      # cambiar de obra ahora
~/.art-wallpaper/venv/bin/python3 rotate.py --id guernica   # forzar una obra
~/.art-wallpaper/venv/bin/python3 rotate.py --selftest      # previews en _preview/ (sin red, sin tocar el fondo)
tail -f ~/.art-wallpaper/rotator.log           # ver el log
./install.sh --uninstall                       # quitar la rotación
```

Requisitos: macOS, `python3` (Command Line Tools) y `curl`. **No usa ImageMagick.** Pillow se
instala solo dentro de un venv aislado en `~/.art-wallpaper/venv`.

## Arquitectura (archivos y flujo)

| Archivo | Rol |
|---|---|
| `rotate.py` | **Todo el motor** en un solo archivo: elige → resuelve ficha → baja imagen → compone → fija el fondo. |
| `artworks.json` | Catálogo de obras (curadas + "auto") con sus fichas/notas. |
| `install.sh` | Instala/desinstala el LaunchAgent; crea el venv. |
| `com.art-wallpaper.rotator.plist.template` | Plantilla del LaunchAgent (launchd), 1800 s. |
| `README.md` | Doc para el usuario. |

**Flujo de una rotación** (`run_once` en `rotate.py`):
1. `pick_artwork` — aleatorio ponderado (favoritas ×4, evita las últimas 12).
2. `resolve_meta` — ficha de la obra (ver abajo).
3. `fetch_image` — descarga la imagen a **resolución original** y la cachea.
4. `get_artist_image` — foto del artista desde Wikidata (opcional, cacheada).
5. `compose` — pared de museo + marco + luz + sombra + `build_card` (la cartela).
6. `set_wallpaper` — osascript a todos los monitores/Spaces.
7. Si una obra falla, se prueba otra (hasta `MAX_ATTEMPTS`): el fondo nunca queda en blanco.

## Modelo de datos: curada vs auto

Cada entrada de `artworks.json` es de uno de dos tipos:

- **Curada**: trae `artist` (y el resto de campos). Se usa **tal cual, sin red** (salvo bajar la
  imagen y, opcionalmente, la foto del artista).
- **Auto (descubrimiento)**: solo `{id, wiki}` + una `note` curada. Los **datos** (autor, año,
  país, técnica, medidas, museo, título ES) se resuelven de **Wikidata** vía SPARQL, cacheados en
  `~/.art-wallpaper/meta/<id>.json`. La **nota** del JSON **siempre manda** sobre el texto de
  Wikipedia (que es seco: "quién la encargó/compró"). Regla de oro: **la nota explica *por qué* la
  obra es famosa** (técnica, escándalo, robo, símbolo, influencia), no su procedencia.

Añadir una obra = una línea: `{ "id": "algo", "wiki": "Título_EN_Wikipedia", "note": "Por qué es célebre..." }`.
`"fav": true` la hace salir más. Para control total, fija cualquier campo a mano.

Campos de ficha: `title, orig, artist, year, country, medium, size, place, note`. País → bandera
por `country_code()`; la bandera se **dibuja** (no emoji). La foto sale de Wikidata (creador → P18).

## Decisiones de diseño (por qué está así)

- **Pillow, no ImageMagick** — una sola dependencia, instalable por pip, y control tipográfico fino.
- **venv propio** (`~/.art-wallpaper/venv`) — el LaunchAgent necesita una ruta de python ESTABLE, y
  evita el PEP 668 de Homebrew y el "--user dentro de venv".
- **Wikidata para datos, notas curadas** — los hechos estructurados los da bien Wikidata; el "por
  qué importa" lo escribe un humano/Claude (Wikipedia lidera con datos aburridos).
- **Banderas dibujadas por código** (`draw_flag`, ~18 países) — sin depender de fuentes de emoji.
- **Estética de museo** — `make_background` (pared greige + textura), `_light_pool` (foco cálido +
  viñeta), `draw_frame` (marco dorado con bisel + sombra), placa marfil con texto oscuro.
- **La pintura manda** — la cartela va en su columna a la derecha, **nunca superpuesta**; se recortó
  su ancho para dar protagonismo a la obra.

## Trampas / lecciones aprendidas (¡importantes!)

- **macOS trae bash 3.2.** En `install.sh` NO pongas un carácter unicode pegado a `$VAR` (p. ej.
  `$VENV…`) bajo `set -u`: lo malinterpreta como "unbound variable". Usa `${VAR}` y ASCII (`...`).
- **Fuentes**: `load_font` cae a *cualquier* TrueType disponible al tamaño pedido si falta el estilo
  (evita el bitmap de 10 px que encogía la nota itálica). En macOS usa Georgia/Helvetica/Arial.
- **Red**: se necesita internet para bajar la obra (Wikipedia/Wikimedia) y los datos/foto (Wikidata).
  Todo se cachea; tras la primera vez, cada obra se recompone offline. Degrada con elegancia.
- **Caché de fichas**: `resolve_meta` cachea en `meta/<id>.json`. Si cambias una `note` en el JSON,
  el código la **sobrescribe** sobre la cacheada (no hace falta borrar caché).
- **Wallpaper por Space**: macOS guarda el fondo por escritorio/Space. `set_wallpaper` lo aplica a
  todos; en ≤ Monterey usa además la BD del Dock (`desktoppicture.db`) + `killall Dock`.
- **Desarrollo sin red (para renders de prueba)**: este proyecto se construyó en un entorno que
  bloqueaba Wikimedia/Wikidata. Truco: hay pinturas y **retratos de artistas** de dominio público en
  repos públicos de GitHub (p. ej. `ntluk/AIArtExtendedPlus` → `Assets/Images/_Artist/`, o
  `Underwater008/Night-at-the-Museum-Unity` → `Assets/PortraitPaints/2D/`). Son git-LFS: bájalos por
  `https://media.githubusercontent.com/media/<owner>/<repo>/<ref>/<path>`. Úsalos para probar
  `compose()` con `meta` construido a mano; NO los metas al repo.

## Cómo probar un cambio

1. `python3 rotate.py --selftest` → genera `_preview/preview-*.jpg` (sin red, sin tocar el fondo).
2. Para probar con una obra real y su ficha completa: `--id <id>` en tu Mac (con red).
3. `python3 -m py_compile rotate.py` y `python3 -c "import json;json.load(open('artworks.json'))"`
   antes de commitear.

## Convenciones

- Un solo archivo de motor (`rotate.py`), plano y legible. Resiste la tentación de sobre-modularizar.
- Español en las cadenas de cara al usuario; inglés en nombres de código.
- Cada obra nueva merece una `note` de "por qué es célebre" (1–2 frases).
- No subas al repo: `_preview/`, `__pycache__/`, imágenes de prueba, `~/.art-wallpaper/`.

## Roadmap

Ver `ROADMAP.md`. Historial en `CHANGELOG.md`.
