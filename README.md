# 🖼️ Art Wallpaper — arte icónico con ficha técnica, cada 30 min

> Proyecto **personal**, por gusto por el arte. Para desarrollarlo/iterar, empieza por
> [`CLAUDE.md`](CLAUDE.md) (memoria del proyecto) y [`ROADMAP.md`](ROADMAP.md).

Cambia el fondo de escritorio de tu Mac cada **30 minutos** por una **pintura icónica**
a **resolución original** (máximo detalle), acompañada de una **cartela de museo** con:
nombre · autor · año · **país** · museo · ciudad · y una **nota grande y legible** que
explica qué representa la obra y por qué importa.

- **Layout de galería:** la pintura **completa, sin recortar**, y a su lado la **cartela**
  en su propia columna — **nunca se superponen** (como un cuadro con su cartelita al lado).
- Fondo de galería (carbón + viñeta) y una tarjeta sobria con hilo dorado.
- **Catálogo abierto para conocer arte:** ~80 obras semilla de todas las épocas y culturas
  (del Bosco y Vermeer a Hopper, Kahlo, Hokusai y Picasso). No es una lista fija: cualquier
  entrada con solo `{id, wiki}` **rellena su ficha automáticamente** desde Wikidata + Wikipedia
  (autor, año, técnica, medidas, museo y nota en español), así que añadir obras es trivial.
- Tus favoritas — **Nighthawks**, **La joven de la perla** y **El caminante sobre el mar de
  nubes** — salen con más frecuencia.

## Instalar (macOS)

```bash
cd art-wallpaper
./install.sh
```

El instalador:
1. Crea un **entorno aislado** (`~/.art-wallpaper/venv`) e instala **Pillow** ahí — así evita
   el PEP 668 de Homebrew y no ensucia tu Python ni tu venv activo.
2. Crea un **LaunchAgent** (`com.art-wallpaper.rotator`) que rota cada 1800 s (30 min).
3. Aplica el primer fondo enseguida.

> Requisitos: macOS, `python3` (viene con las *Command Line Tools*: `xcode-select --install`)
> y `curl` (nativo). No usa ImageMagick. Necesita internet solo para **descargar** cada obra;
> una vez en caché, se recompone sin red.

## Uso

Los comandos manuales usan el Python del venv (`~/.art-wallpaper/venv/bin/python3`):

```bash
PY=~/.art-wallpaper/venv/bin/python3
$PY rotate.py --once              # cambiar de obra ahora
$PY rotate.py --id nighthawks     # forzar una obra concreta (ver ids en artworks.json)
$PY rotate.py --selftest          # genera previews en _preview/ sin red ni tocar el fondo
tail -f ~/.art-wallpaper/rotator.log  # ver el log
./install.sh --uninstall          # quitar la rotación
```

## ¿Cómo elige y baja las obras?

- El catálogo vive en [`artworks.json`](artworks.json). Hay dos tipos de entrada:
  - **Curada:** trae todos los campos de la ficha (`title`, `artist`, `year`, `medium`, `size`,
    `place`, `note`). Se usa tal cual, sin depender de nada externo salvo bajar la imagen.
  - **Auto (descubrimiento):** solo `{id, wiki}`. La ficha se **resuelve automáticamente** en la
    primera aparición: `en.wikipedia` (imagen original + Q-id) → **Wikidata** (autor, año,
    técnica, medidas, museo, vía una consulta SPARQL con etiquetas en español) → `es.wikipedia`
    (nota). El resultado se **cachea** en `~/.art-wallpaper/meta/<id>.json` (se resuelve una vez).
- La imagen se baja a **resolución original** y se **cachea** en `~/.art-wallpaper/cache/`.
- La selección es **aleatoria ponderada**: evita repetir las últimas 12 y da x4 de peso a las
  favoritas (`"fav": true`). Si una obra falla (título malo, sin red), prueba con otra —el fondo
  nunca queda en blanco.

## Personalizar

- **Añadir una obra (fácil):** agrega `{"id": "algo", "wiki": "Título_en_Wikipedia_EN"}` a
  `artworks.json` y listo: la ficha se rellena sola desde Wikidata. Añade `"fav": true` para que
  salga más. Para control total, puedes fijar cualquier campo a mano (`title`, `artist`, `year`,
  `medium`, `size`, `place`, `note`) y `"file"` como *fallback* de imagen (archivo de Commons).
- **Cambiar el intervalo:** edita `StartInterval` en la plantilla del plist (segundos) y
  reinstala (`./install.sh`).
- **Resolución del fondo:** se detecta con `system_profiler`. Puedes forzarla con
  `ART_W`/`ART_H` (variables de entorno).

## Archivos

| Archivo | Qué es |
|---|---|
| `rotate.py` | Motor: elige, descarga, compone la cartela y fija el fondo. |
| `artworks.json` | Catálogo de obras + fichas/notas. |
| `install.sh` | Instala/desinstala el LaunchAgent (crea el venv). |
| `com.art-wallpaper.rotator.plist.template` | Plantilla del LaunchAgent (launchd). |
| `CLAUDE.md` | Memoria/manual del proyecto (para iterar con Claude o a mano). |
| `ROADMAP.md` · `CHANGELOG.md` | Ideas pendientes · historial. |
| `init-repo.sh` | Convierte la carpeta en un repo git independiente. |
| `LICENSE` | MIT (cubre el código, no las obras de arte). |

## Iterar / desarrollar

Lee [`CLAUDE.md`](CLAUDE.md): explica la arquitectura, el modelo curada/auto, las decisiones y las
trampas (bash 3.2 de macOS, fuentes, red/caché, imágenes de prueba). Ideas en [`ROADMAP.md`](ROADMAP.md).
