#!/usr/bin/env python3
"""
Rotador de fondo de escritorio con arte icónico + ficha técnica (estilo cartela de museo).

Objetivo: CONOCER ARTE a través del fondo. El catálogo (artworks.json) no está limitado a un
puñado de obras curadas: cualquier entrada con solo {id, wiki} baja su imagen a resolución
original y RELLENA la ficha automáticamente desde Wikidata + Wikipedia (autor, año, técnica,
medidas, museo, nota en español), cacheando el resultado. Así el catálogo crece sin esfuerzo.

Flujo por ejecución:
  1. Elige una obra (aleatorio ponderado; favoritas con más peso; evita repetir).
  2. Resuelve su ficha (curada en el JSON, o auto desde Wikidata — cacheada).
  3. Descarga la imagen a RESOLUCIÓN ORIGINAL (máximo detalle). Cachea en disco.
  4. Compone: pintura completa (sin recortar) sobre fondo de galería + tarjeta con la ficha.
  5. Fija el resultado como fondo en todos los monitores (macOS, vía osascript).
  Si una obra falla (título malo, sin red), prueba con otra: el fondo nunca queda en blanco.

Uso:
  python3 rotate.py                 # rotación normal (lo que corre launchd cada 30 min)
  python3 rotate.py --id nighthawks # fuerza una obra
  python3 rotate.py --selftest      # previews (horizontal + vertical) sin red ni tocar el fondo

Requisitos en el Mac: python3 (con Pillow) + curl. Sin ImageMagick.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    sys.exit("Falta Pillow. Instala con:  python3 -m pip install --user pillow")

# ---------------------------------------------------------------------------
# Rutas / configuración
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("ART_HOME", Path.home() / ".art-wallpaper")).expanduser()
CACHE_DIR = HOME / "cache"        # imágenes originales descargadas (se reutilizan)
META_DIR = HOME / "meta"          # fichas resueltas por auto-ficha (se reutilizan)
OUT_DIR = HOME / "current"        # wallpapers ya compuestos (se conservan los últimos)
STATE_FILE = HOME / "state.json"  # obras mostradas recientemente (para no repetir)
CATALOG = HERE / "artworks.json"

USER_AGENT = "art-wallpaper/1.1 (personal desktop art rotator)"
RECENT_MEMORY = 12                # mínimo de obras recientes a evitar (ver recent_window)
RECENT_FRACTION = 0.6             # ...o el 60% del catálogo, lo que sea mayor
FAV_WEIGHT = 2                    # peso de una obra favorita frente a 1 de una normal
MAX_ATTEMPTS = 8                  # obras a intentar antes de rendirse en una rotación

# Caché en disco: las imágenes se guardan YA reducidas a lo que la pantalla usa,
# y el total tiene techo (se borran las menos usadas). Ver shrink_image/prune_cache.
ART_MAX_SIDE = 2200               # px del lado largo de una pintura cacheada
ART_QUALITY = 88
FACE_MAX_SIDE = 420               # px del retrato del artista (se pinta a ~110 px)
FACE_QUALITY = 88
CACHE_BUDGET_MB = 250             # techo del caché de imágenes (cache/ + meta/*.img)
MIN_ART_SIDE = 1000               # por debajo de esto la obra se ve pixelada enmarcada

# Estética — sala contemporánea tipo white cube (Tate Modern / MoMA / Pompidou):
# pared plana sin degradados de foco, marco fino y plano, y la cartela IMPRESA en la
# pared (sin tarjeta flotante). Todo el texto en una sans neutra.
WALL_TOP = (243, 242, 239)      # blanco de galería, apenas cálido
WALL_BOT = (232, 230, 226)      # caída mínima hacia el suelo
WALL_LIGHT = (252, 251, 249)    # lavado de luz cenital, casi imperceptible
FRAME_DARK = (26, 25, 23)       # marco fino, negro neutro
FRAME_EDGE = (58, 56, 52)       # canto superior del marco (una línea de luz)
INK = (24, 23, 21)              # texto principal
INK_SOFT = (74, 71, 67)         # nota
INK_MUTED = (124, 120, 114)     # datos secundarios
HAIRLINE = (200, 197, 191)      # filete de separación
PAINTING_PAD = 0.062

# Variante oscura: pon DARK_ROOM = True para una sala de paredes grafito.
DARK_ROOM = False
if DARK_ROOM:
    WALL_TOP, WALL_BOT, WALL_LIGHT = (38, 37, 35), (28, 27, 26), (52, 50, 47)
    FRAME_DARK, FRAME_EDGE = (232, 230, 226), (255, 255, 255)
    INK, INK_SOFT, INK_MUTED, HAIRLINE = ((240, 238, 234), (196, 192, 186),
                                          (150, 146, 140), (74, 71, 67))


# ---------------------------------------------------------------------------
# HTTP (curl) helpers
# ---------------------------------------------------------------------------
def _curl(url: str, dest: Path, timeout: int = 60) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["curl", "-sSL", "--fail", "--max-time", str(timeout),
             "-A", USER_AGENT, "-o", str(dest), url],
            check=True,
        )
        return dest.exists() and dest.stat().st_size > 512
    except subprocess.CalledProcessError:
        return False


def _thumb_url(url: str, width: int) -> str | None:
    """Reescribe una URL de Wikimedia a su miniatura de ancho `width`, para no bajar
    un TIFF de 80 MB cuando la pantalla usa 2.600 px. None si la URL no es de Commons."""
    m = re.match(r"(https://upload\.wikimedia\.org/wikipedia/[^/]+)/([0-9a-f])/([0-9a-f]{2})/(.+)$", url)
    if not m or "/thumb/" in url:
        return None
    base, d1, d2, name = m.groups()
    thumb = f"{width}px-{name}"
    if not name.lower().endswith((".jpg", ".jpeg", ".png")):
        thumb += ".jpg"          # tif/svg/webp se sirven convertidos
    return f"{base}/thumb/{d1}/{d2}/{name}/{thumb}"


def shrink_image(path: Path, max_side: int, quality: int) -> Path:
    """Deja en disco SOLO la versión que el compositor necesita: JPEG, lado largo
    acotado. Es la diferencia entre 300 MB de caché y 30 MB."""
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None   # las fuentes son Wikimedia; un TIFF enorme no es un ataque
        with Image.open(path) as im:
            im.load()
            w, h = im.size
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            if max(w, h) > max_side:
                k = max_side / max(w, h)
                im = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
            elif path.suffix and im.format == "JPEG" and path.stat().st_size < 3_000_000:
                return path      # ya es pequeña y es JPEG: no la toques
            tmp = path.with_suffix(".tmp")
            im.save(tmp, "JPEG", quality=quality, optimize=True, progressive=True)
        tmp.replace(path)
    except Exception as e:       # noqa: BLE001 — una imagen rara no puede tumbar la rotación
        print(f"[shrink] {path.name}: {e} — descartada, se volverá a bajar", file=sys.stderr)
        try:
            path.unlink()        # sólo es caché: mejor re-bajarla que arrastrar un fichero roto
        except OSError:
            pass
    return path


def _cache_files() -> list[Path]:
    return [p for p in list(CACHE_DIR.glob("*.img")) + list(META_DIR.glob("*.img")) if p.is_file()]


def prune_cache(budget_mb: int = CACHE_BUDGET_MB) -> int:
    """Techo duro del caché: borra las imágenes menos usadas hasta bajar del presupuesto.
    'Menos usada' = mtime más antiguo; fetch_image toca el fichero cada vez que lo reusa."""
    files = sorted(_cache_files(), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    budget = budget_mb * 1024 * 1024
    freed = 0
    while total > budget and len(files) > 1:
        old = files.pop(0)
        try:
            n = old.stat().st_size
            old.unlink()
            total -= n
            freed += n
        except OSError:
            pass
    return freed


def compact_cache() -> None:
    """Pasada única sobre el caché ya existente: reduce todo y aplica el techo."""
    before = sum(p.stat().st_size for p in _cache_files())
    for p in sorted(CACHE_DIR.glob("*.img")):
        shrink_image(p, ART_MAX_SIDE, ART_QUALITY)
    for p in sorted(META_DIR.glob("*.img")):
        shrink_image(p, FACE_MAX_SIDE, FACE_QUALITY)
    prune_cache()
    after = sum(p.stat().st_size for p in _cache_files())
    mb = lambda n: f"{n / 1024 / 1024:.0f} MB"  # noqa: E731
    print(f"Caché compactado: {mb(before)} -> {mb(after)} ({len(_cache_files())} imágenes)")


def _get_json(url: str, timeout: int = 25, tries: int = 3):
    """Wikipedia y Wikidata devuelven 429/400 cuando se les pide de más. Reintenta con
    espera: un fallo pasajero no debe convertirse en una ficha vacía cacheada para siempre."""
    for attempt in range(tries):
        try:
            out = subprocess.run(
                ["curl", "-sSL", "--fail", "--max-time", str(timeout), "-A", USER_AGENT, url],
                check=True, capture_output=True, text=True,
            ).stdout
            return json.loads(out)
        except (subprocess.CalledProcessError, ValueError):
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
    return None


# ---------------------------------------------------------------------------
# Fuentes (macOS primero, DejaVu como fallback para pruebas)
# ---------------------------------------------------------------------------
# Una sans neutra para TODO, como en las cartelas de una sala contemporánea.
# Los .ttc de macOS son colecciones: (ruta, índice de la variante).
_HNEUE = "/System/Library/Fonts/HelveticaNeue.ttc"
_AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
FONT_CANDIDATES = {
    "ui_thin":   [(_HNEUE, 12), (_AVENIR, 10), "/System/Library/Fonts/Supplemental/Arial.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "ui_light":  [(_HNEUE, 7), (_AVENIR, 7), "/System/Library/Fonts/Supplemental/Arial.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "ui":        [(_HNEUE, 0), (_AVENIR, 7), "/System/Library/Fonts/Supplemental/Arial.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "ui_medium": [(_HNEUE, 10), (_AVENIR, 5), "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "ui_bold":   [(_HNEUE, 1), (_AVENIR, 0), "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "ui_italic": [(_HNEUE, 8), (_AVENIR, 4),
                  "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"],
}


_ANY_TTF = None


def _any_ttf() -> str | None:
    """Primera fuente TrueType disponible de cualquier categoría (fallback universal)."""
    global _ANY_TTF
    if _ANY_TTF is not None:
        return _ANY_TTF or None
    for cands in FONT_CANDIDATES.values():
        for p in cands:
            if os.path.exists(p):
                _ANY_TTF = p
                return p
    _ANY_TTF = ""
    return None


def load_font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for cand in FONT_CANDIDATES[kind]:
        path, index = cand if isinstance(cand, tuple) else (cand, 0)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=index)
            except OSError:
                continue
    # Estilo no disponible: usa CUALQUIER TrueType al tamaño pedido (nunca el bitmap de 10px).
    p = _any_ttf()
    if p:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Estado (evitar repeticiones)
# ---------------------------------------------------------------------------
def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {"recent": []}


def write_state(state: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Catálogo + selección
# ---------------------------------------------------------------------------
def load_catalog() -> list:
    return json.loads(CATALOG.read_text())["artworks"]


def recent_window(catalog_size: int) -> int:
    """Cuántas obras recientes se vetan. Con 48 rotaciones al día, una ventana de 12
    deja que un cuadro vuelva a las 6 horas; al 60% del catálogo tarda ~2 días."""
    return max(RECENT_MEMORY, min(catalog_size - 2, int(catalog_size * RECENT_FRACTION)))


def pick_artwork(catalog: list, exclude: set):
    import random
    usable = [a for a in catalog if not a.get("skip")] or catalog
    pool = [a for a in usable if a["id"] not in exclude] or usable
    weights = [FAV_WEIGHT if a.get("fav") else 1 for a in pool]
    return random.choices(pool, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Auto-ficha: Wikipedia REST + Wikidata (para entradas mínimas {id, wiki})
# ---------------------------------------------------------------------------
def _fmt_dim(v: str) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    s = f"{f:.1f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _year_from(inception: str) -> str:
    m = re.search(r"(-?\d{1,4})", inception or "")
    if not m:
        return ""
    y = int(m.group(1))
    return f"{abs(y)} a. C." if y < 0 else str(y)


def wiki_summary(title: str, lang: str = "en"):
    t = urllib.parse.quote(title.replace("_", " "), safe="")
    return _get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{t}")


def wikidata_facts(qid: str) -> dict:
    """Una consulta SPARQL: etiquetas en español ya resueltas + dimensiones + título es + nota."""
    query = f"""
SELECT ?creatorLabel ?inception ?materialLabel ?locationLabel ?collectionLabel
       ?originLabel ?creatorCountryLabel ?height ?width ?esTitle ?itemDescription WHERE {{
  BIND(wd:{qid} AS ?item)
  OPTIONAL {{ ?item wdt:P170 ?creator. OPTIONAL {{ ?creator wdt:P27 ?creatorCountry. }} }}
  OPTIONAL {{ ?item wdt:P571 ?inception. }}
  OPTIONAL {{ ?item wdt:P186 ?material. }}
  OPTIONAL {{ ?item wdt:P276 ?location. }}
  OPTIONAL {{ ?item wdt:P195 ?collection. }}
  OPTIONAL {{ ?item wdt:P495 ?origin. }}
  OPTIONAL {{ ?item wdt:P2048 ?height. }}
  OPTIONAL {{ ?item wdt:P2049 ?width. }}
  OPTIONAL {{ ?esArt schema:about ?item ; schema:isPartOf <https://es.wikipedia.org/> ;
                     schema:name ?esTitle. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en,de,fr". }}
}} LIMIT 1
""".strip()
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(query)
    doc = _get_json(url, timeout=30)
    if not doc:
        return {}
    rows = doc.get("results", {}).get("bindings", [])
    if not rows:
        return {}
    r = rows[0]
    val = lambda k: r.get(k, {}).get("value", "")
    place = val("locationLabel") or val("collectionLabel")
    country = val("originLabel") or val("creatorCountryLabel")
    if country.lower() in ("apátrida", "apatrida", "stateless"):
        country = ""
    dims = ""
    if val("height") and val("width"):
        hh, ww = val("height"), val("width")
        try:  # algunas fichas vienen en metros: un cuadro de "3,4 cm" no existe
            if max(float(hh), float(ww)) < 12:
                hh, ww = str(float(hh) * 100), str(float(ww) * 100)
        except (TypeError, ValueError):
            pass
        dims = f"{_fmt_dim(hh)} × {_fmt_dim(ww)} cm"
    return {
        "artist": val("creatorLabel"),
        "year": _year_from(val("inception")),
        "country": country,
        "medium": val("materialLabel"),
        "size": dims,
        "place": place,
        "esTitle": val("esTitle"),
        "desc": val("itemDescription"),
    }


def _trim_note(text: str, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    dot = cut.rfind(". ")
    return (cut[: dot + 1] if dot > 80 else cut.rstrip() + "…")


def resolve_meta(art: dict) -> dict:
    """Devuelve la ficha (curada tal cual, o auto-resuelta + cacheada) e 'image_url' sugerida."""
    # Curada: tiene 'artist' -> usa los campos del JSON (sin depender de Wikidata).
    if art.get("artist"):
        meta = {k: art.get(k, "") for k in
                ("title", "orig", "artist", "year", "country", "medium", "size", "place", "note")}
        meta["image_url"] = None
        return meta

    # Auto: cache primero (pero la nota curada del JSON siempre manda si existe)
    cache = META_DIR / f"{art['id']}.json"
    if cache.exists():
        try:
            meta = json.loads(cache.read_text())
            # Una ficha sin autor es el residuo de una consulta fallida a Wikidata: no la
            # damos por buena, se vuelve a resolver (si vuelve a fallar, se usa igual).
            if meta.get("artist"):
                if art.get("note"):
                    meta["note"] = art["note"]
                return meta
        except ValueError:
            meta = None

    summ = wiki_summary(art["wiki"], "en")
    if not summ:
        raise RuntimeError(f"sin summary EN para {art['id']}")
    qid = summ.get("wikibase_item", "")
    facts = wikidata_facts(qid) if qid else {}

    # La nota curada (por qué la obra es célebre) tiene prioridad sobre el extracto de Wikipedia.
    note = art.get("note") or ""
    if not note:
        if facts.get("esTitle"):
            es = wiki_summary(facts["esTitle"], "es")
            if es and es.get("extract"):
                note = _trim_note(es["extract"])
        if not note:
            note = _trim_note(facts.get("desc") or summ.get("extract") or "")

    en_title = summ.get("title", art["wiki"].replace("_", " "))
    es_title = facts.get("esTitle") or en_title
    meta = {
        "title": es_title,
        "orig": en_title if en_title and en_title != es_title else "",
        "artist": facts.get("artist", ""),
        "year": facts.get("year", ""),
        "country": facts.get("country", ""),
        "medium": (facts.get("medium") or "").capitalize(),
        "size": facts.get("size", ""),
        "place": facts.get("place", ""),
        "note": note,
        "image_url": (summ.get("originalimage") or summ.get("thumbnail") or {}).get("source"),
    }
    META_DIR.mkdir(parents=True, exist_ok=True)
    if facts.get("artist") or not qid:
        cache.write_text(json.dumps(meta, ensure_ascii=False, indent=2))  # sólo cacheamos lo bueno
    return meta


def get_artist_image(art: dict, meta: dict) -> Path | None:
    """Foto/retrato del artista desde Wikidata (creador P170 → imagen P18). Cacheada por
    artista. Devuelve None si no se encuentra o no hay red (la placa simplemente lo omite)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (meta.get("artist") or "").lower()).strip("-")
    if not slug:
        return None
    cached = META_DIR / f"artist-{slug}.img"
    if cached.exists() and cached.stat().st_size > 512:
        os.utime(cached, None)
        return cached

    summ = wiki_summary(art["wiki"], "en")
    qid = summ.get("wikibase_item", "") if summ else ""
    if not qid:
        return None
    q = f"SELECT ?img WHERE {{ wd:{qid} wdt:P170 ?c. ?c wdt:P18 ?img. }} LIMIT 1"
    doc = _get_json("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q), 25)
    try:
        url = doc["results"]["bindings"][0]["img"]["value"]
    except (TypeError, KeyError, IndexError):
        return None
    META_DIR.mkdir(parents=True, exist_ok=True)
    thumb = _thumb_url(url, FACE_MAX_SIDE)
    if thumb and _curl(thumb, cached):
        return shrink_image(cached, FACE_MAX_SIDE, FACE_QUALITY)
    return shrink_image(cached, FACE_MAX_SIDE, FACE_QUALITY) if _curl(url, cached) else None


# ---------------------------------------------------------------------------
# Descarga de la imagen (resolución ORIGINAL)
# ---------------------------------------------------------------------------
def fetch_image(art: dict, image_url_hint: str | None) -> Path:
    cached = CACHE_DIR / f"{art['id']}.img"
    if cached.exists() and cached.stat().st_size > 512:
        os.utime(cached, None)   # marca de uso: el techo del caché borra lo menos usado
        return cached

    urls = []
    if image_url_hint:
        urls.append(image_url_hint)
    summ = wiki_summary(art["wiki"], "en")
    if summ:
        src = (summ.get("originalimage") or summ.get("thumbnail") or {}).get("source")
        if src:
            urls.append(src)
    if art.get("file"):
        urls.append("https://commons.wikimedia.org/wiki/Special:FilePath/"
                    + urllib.parse.quote(art["file"], safe=""))

    for u in urls:
        thumb = _thumb_url(u, ART_MAX_SIDE)
        if (thumb and _curl(thumb, cached)) or _curl(u, cached):
            img = shrink_image(cached, ART_MAX_SIDE, ART_QUALITY)
            side = _long_side(img)
            if side and side < MIN_ART_SIDE:
                # Muchas obras del siglo XX solo tienen en Wikipedia una imagen de uso
                # legítimo de pocos cientos de px: enmarcada se vería pixelada.
                img.unlink(missing_ok=True)
                raise RuntimeError(f"imagen demasiado pequeña ({side} px) para '{art['id']}'")
            return img
    raise RuntimeError(f"No se pudo descargar la imagen de '{art['id']}'.")


def _long_side(path: Path) -> int:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return max(im.size)
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
# Resolución de pantalla
# ---------------------------------------------------------------------------
def screen_size() -> tuple[int, int]:
    ew, eh = os.environ.get("ART_W"), os.environ.get("ART_H")
    if ew and eh:
        return int(ew), int(eh)
    try:
        out = subprocess.run(["system_profiler", "SPDisplaysDataType"],
                             capture_output=True, text=True, timeout=15).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Resolution:"):
                parts = line.replace("Resolution:", "").split()
                return int(parts[0]), int(parts[2])
    except Exception:
        pass
    return 2880, 1800


# ---------------------------------------------------------------------------
# Composición
# ---------------------------------------------------------------------------
def make_background(w: int, h: int) -> Image.Image:
    """Pared de white cube: blanca, plana y mate. Sin degradado de foco: la caída
    vertical es de una decena de niveles y el grano evita que se vea digital."""
    top = Image.new("RGB", (w, h), WALL_TOP)
    bot = Image.new("RGB", (w, h), WALL_BOT)
    m = Image.new("L", (1, h))
    for y in range(h):
        m.putpixel((0, y), int(255 * (y / h) ** 1.6))
    wall = Image.composite(bot, top, m.resize((w, h)))
    noise = Image.effect_noise((w, h), 10).convert("RGB")
    return Image.blend(wall, noise, 0.022)


def _wall_light(wall: Image.Image, cx: int, top_y: int, rx: int) -> Image.Image:
    """Lavado de luz cenital sobre la obra. Un museo moderno ilumina parejo: esto es
    un 4% de aclarado, no el halo de un foco. Sin viñeta en las esquinas."""
    w, h = wall.size
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse([cx - rx, top_y - int(h * 0.55), cx + rx, top_y + int(h * 0.45)],
                                 fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=min(w, h) // 3))
    lit = Image.new("RGB", (w, h), WALL_LIGHT)
    return Image.composite(lit, wall, glow.point(lambda v: int(v * 0.42)))


def draw_frame(canvas: Image.Image, x: int, y: int, iw: int, ih: int, t: int) -> None:
    """Marco de galería contemporánea: una banda fina, plana y negra. Sin bisel, sin
    dorado, sin brillo. Toda la profundidad la da la sombra de contacto, no el marco."""
    d = ImageDraw.Draw(canvas)
    d.rectangle([x - t, y - t, x + iw + t - 1, y + ih + t - 1], fill=FRAME_DARK)
    # una sola línea de luz en el canto superior: basta para que el marco tenga cuerpo
    d.line([x - t, y - t, x + iw + t - 1, y - t], fill=FRAME_EDGE, width=max(1, t // 6))


def wrap_text(text, font, max_w, draw) -> list:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


_FLAG_KEYS = [
    (("países bajos", "netherlands", "holanda"), "nl"),
    (("alemania", "germany"), "de"),
    (("francia", "france"), "fr"),
    (("italia", "italy"), "it"),
    (("bélgica", "belgium", "belgica"), "be"),
    (("españa", "spain", "espana"), "es"),
    (("austria",), "at"),
    (("japón", "japan", "japon"), "jp"),
    (("noruega", "norway"), "no"),
    (("suecia", "sweden"), "se"),
    (("dinamarca", "denmark"), "dk"),
    (("finlandia", "finland"), "fi"),
    (("suiza", "switzerland"), "ch"),
    (("reino unido", "united kingdom", "inglaterra", "gran bretaña", "england"), "gb"),
    (("estados unidos", "united states", "ee. uu", "eeuu"), "us"),
    (("rusia", "russia", "unión soviética", "soviet"), "ru"),
    (("méxico", "mexico"), "mx"),
    (("grecia", "greece"), "gr"),
]


def country_code(name: str) -> str:
    n = (name or "").lower()
    for keys, code in _FLAG_KEYS:
        if any(k in n for k in keys):
            return code
    return ""


def draw_flag(code: str, w: int, h: int):
    """Dibuja una bandera pequeña (sin depender de fuentes de emoji). None si no se conoce."""
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)

    def hbands(cs):
        for i, c in enumerate(cs):
            d.rectangle([0, h * i // len(cs), w, h * (i + 1) // len(cs)], fill=c)

    def vbands(cs):
        for i, c in enumerate(cs):
            d.rectangle([w * i // len(cs), 0, w * (i + 1) // len(cs), h], fill=c)

    def nordic(field, cross):
        d.rectangle([0, 0, w, h], fill=field)
        cw = max(2, int(h * 0.20)); cx = int(w * 0.36)
        d.rectangle([cx - cw, 0, cx + cw, h], fill=cross)
        d.rectangle([0, h // 2 - cw, w, h // 2 + cw], fill=cross)

    if code == "nl":
        hbands([(174, 28, 40), (255, 255, 255), (33, 70, 139)])
    elif code == "de":
        hbands([(0, 0, 0), (221, 0, 0), (255, 206, 0)])
    elif code == "ru":
        hbands([(255, 255, 255), (0, 57, 166), (213, 43, 30)])
    elif code == "fr":
        vbands([(0, 85, 164), (255, 255, 255), (239, 65, 53)])
    elif code == "it":
        vbands([(0, 146, 70), (255, 255, 255), (206, 43, 55)])
    elif code == "be":
        vbands([(0, 0, 0), (253, 218, 36), (239, 51, 64)])
    elif code == "mx":
        vbands([(0, 104, 71), (255, 255, 255), (206, 17, 38)])
    elif code == "at":
        hbands([(237, 41, 57), (255, 255, 255), (237, 41, 57)])
    elif code == "es":
        d.rectangle([0, 0, w, h], fill=(198, 11, 30))
        d.rectangle([0, h // 4, w, 3 * h // 4], fill=(255, 196, 0))
    elif code == "jp":
        r = int(h * 0.30)
        d.ellipse([w // 2 - r, h // 2 - r, w // 2 + r, h // 2 + r], fill=(188, 0, 45))
    elif code == "no":
        nordic((186, 12, 47), (255, 255, 255))
        bw = max(1, int(h * 0.09)); cx = int(w * 0.36)
        d.rectangle([cx - bw, 0, cx + bw, h], fill=(0, 32, 91))
        d.rectangle([0, h // 2 - bw, w, h // 2 + bw], fill=(0, 32, 91))
    elif code == "se":
        nordic((0, 106, 167), (254, 204, 0))
    elif code == "dk":
        nordic((198, 12, 48), (255, 255, 255))
    elif code == "fi":
        nordic((255, 255, 255), (0, 53, 128))
    elif code == "ch":
        d.rectangle([0, 0, w, h], fill=(213, 43, 30))
        aw = max(2, int(h * 0.16))
        d.rectangle([w // 2 - aw, int(h * 0.28), w // 2 + aw, int(h * 0.72)], fill=(255, 255, 255))
        d.rectangle([int(w * 0.30), h // 2 - aw, int(w * 0.70), h // 2 + aw], fill=(255, 255, 255))
    elif code == "us":
        for i in range(13):
            d.rectangle([0, h * i // 13, w, h * (i + 1) // 13],
                        fill=(178, 34, 52) if i % 2 == 0 else (255, 255, 255))
        d.rectangle([0, 0, int(w * 0.42), h * 7 // 13], fill=(60, 59, 110))
    elif code == "gb":
        d.rectangle([0, 0, w, h], fill=(1, 33, 105))
        d.line([0, 0, w, h], fill=(255, 255, 255), width=max(3, int(h * 0.26)))
        d.line([w, 0, 0, h], fill=(255, 255, 255), width=max(3, int(h * 0.26)))
        d.line([0, 0, w, h], fill=(200, 16, 46), width=max(1, int(h * 0.11)))
        d.line([w, 0, 0, h], fill=(200, 16, 46), width=max(1, int(h * 0.11)))
        d.rectangle([w // 2 - int(h * 0.20), 0, w // 2 + int(h * 0.20), h], fill=(255, 255, 255))
        d.rectangle([0, h // 2 - int(h * 0.20), w, h // 2 + int(h * 0.20)], fill=(255, 255, 255))
        d.rectangle([w // 2 - int(h * 0.10), 0, w // 2 + int(h * 0.10), h], fill=(200, 16, 46))
        d.rectangle([0, h // 2 - int(h * 0.10), w, h // 2 + int(h * 0.10)], fill=(200, 16, 46))
    else:
        return None
    ImageDraw.Draw(im).rectangle([0, 0, w - 1, h - 1], outline=HAIRLINE)
    return im.convert("RGBA")


def circle_portrait(img: Image.Image, d: int) -> Image.Image:
    """Recorte circular (sesgado hacia arriba, donde suele estar la cara) con aro dorado."""
    im = img.convert("RGB")
    s = min(im.size)
    left = (im.width - s) // 2
    top = int((im.height - s) * 0.22)
    im = im.crop((left, top, left + s, top + s)).resize((d, d), Image.LANCZOS)
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, d - 1, d - 1], fill=255)
    out = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    ImageDraw.Draw(out).ellipse([0, 0, d - 1, d - 1], outline=HAIRLINE, width=max(1, d // 60))
    return out


def build_label(meta: dict, col_w: int, scale: float) -> Image.Image:
    """Cartela de sala contemporánea: texto impreso DIRECTAMENTE en la pared, sin
    tarjeta, sin marco y sin sombra. Todo en una sans neutra, alineado a la izquierda,
    y la jerarquía la da el tamaño y el gris, no los adornos."""
    f_title = load_font("ui_light", int(46 * scale))
    f_orig = load_font("ui_italic", int(23 * scale))
    f_artist = load_font("ui_medium", int(30 * scale))
    f_meta = load_font("ui_light", int(21 * scale))    # año · país
    f_small = load_font("ui_light", int(20 * scale))   # técnica, museo
    f_note = load_font("ui_light", int(26 * scale))

    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    title = meta.get("title") or "Obra sin título"
    title_lines = wrap_text(title, f_title, col_w, probe)
    orig = meta.get("orig") or ""
    show_orig = bool(orig) and orig.lower() not in title.lower()

    artist = meta.get("artist") or ""
    yc_line = " · ".join([b for b in (meta.get("year"), meta.get("country")) if b])
    place_line = meta.get("place") or ""
    tech_line = " · ".join([b for b in (meta.get("medium"), meta.get("size")) if b])

    def lh(font, k=1.22):
        asc, desc = font.getmetrics()
        return int((asc + desc) * k)

    gap_xs, gap_s, gap_m, gap_l = (int(6 * scale), int(12 * scale),
                                   int(26 * scale), int(38 * scale))

    portrait = None
    ap = meta.get("artist_img")
    if ap:
        try:
            portrait = ap if isinstance(ap, Image.Image) else Image.open(ap)
        except Exception:  # noqa: BLE001
            portrait = None
    iso = country_code(meta.get("country"))
    fh = int(f_meta.size * 0.78)
    flag = draw_flag(iso, int(fh * 1.5), fh) if iso else None

    block_h = (lh(f_artist) if artist else 0) + ((gap_xs + lh(f_meta)) if yc_line else 0)
    d_ph = int(block_h * 0.92) if (portrait is not None and block_h > 0) else 0
    x_text = (d_ph + int(20 * scale)) if d_ph else 0

    note_lines = wrap_text(meta["note"], f_note, col_w, probe) if meta.get("note") else []

    # alto total (se mide antes de pintar para poder centrar/alinear el bloque)
    y = 0
    for _ in title_lines:
        y += lh(f_title, 1.16)
    if show_orig:
        y += gap_xs + lh(f_orig)
    if block_h:
        y += gap_l + block_h
    if tech_line:
        y += gap_m + lh(f_small)
    if place_line:
        y += (gap_xs if tech_line else gap_m) + lh(f_small)
    if note_lines:
        y += gap_l + gap_m
        for _ in note_lines:
            y += lh(f_note, 1.45)
    label = Image.new("RGBA", (col_w, max(1, y)), (0, 0, 0, 0))
    d = ImageDraw.Draw(label)

    y = 0
    for line in title_lines:
        d.text((0, y), line, font=f_title, fill=INK + (255,))
        y += lh(f_title, 1.16)
    if show_orig:
        y += gap_xs
        d.text((0, y), orig, font=f_orig, fill=INK_MUTED + (255,))
        y += lh(f_orig)

    if block_h:
        y += gap_l
        block_top = y
        if d_ph:
            label.alpha_composite(circle_portrait(portrait, d_ph), (0, block_top))
        if artist:
            d.text((x_text, y), artist, font=f_artist, fill=INK + (255,))
            y += lh(f_artist)
        if yc_line:
            if artist:
                y += gap_xs
            d.text((x_text, y), yc_line, font=f_meta, fill=INK_MUTED + (255,))
            if flag is not None:
                fx = x_text + int(probe.textlength(yc_line, font=f_meta)) + int(11 * scale)
                fy = y + (lh(f_meta) - fh) // 2 - int(2 * scale)
                if fx + flag.width <= col_w:
                    label.alpha_composite(flag, (fx, fy))
            y += lh(f_meta)
        y = max(y, block_top + block_h)

    if tech_line:
        y += gap_m
        d.text((0, y), tech_line, font=f_small, fill=INK_MUTED + (255,))
        y += lh(f_small)
    if place_line:
        y += gap_xs if tech_line else gap_m
        d.text((0, y), place_line, font=f_small, fill=INK_MUTED + (255,))
        y += lh(f_small)

    if note_lines:
        y += gap_l
        d.rectangle([0, y, int(54 * scale), y + max(1, int(1.5 * scale))], fill=HAIRLINE + (255,))
        y += gap_m
        for line in note_lines:
            d.text((0, y), line, font=f_note, fill=INK_SOFT + (255,))
            y += lh(f_note, 1.45)
    return label


def compose(meta: dict, img_path: Path, w: int, h: int) -> Image.Image:
    """Una sala contemporánea: pared blanca y plana, la obra con un marco fino y negro
    y su sombra de contacto, y la cartela impresa en la pared a su derecha."""
    scale = h / 1800.0
    pad = int(min(w, h) * PAINTING_PAD)
    gap = int(pad * 1.15)
    frame_t = max(5, int(min(w, h) * 0.0055))

    col_w = int(min(max(w * 0.255, 560), 780))
    label = build_label(meta, col_w, scale)

    # La obra vive a la IZQUIERDA de la columna de texto; nunca se tocan.
    area_x0 = pad + frame_t
    area_x1 = w - pad - (col_w + gap)
    avail_w = max(1, area_x1 - area_x0)
    avail_h = h - 2 * (pad + frame_t)

    painting = Image.open(img_path).convert("RGB")
    pw, ph = painting.size
    ratio = min(avail_w / pw, avail_h / ph)
    new_w, new_h = max(1, int(pw * ratio)), max(1, int(ph * ratio))
    painting = painting.resize((new_w, new_h), Image.LANCZOS)
    px = area_x0 + (avail_w - new_w) // 2
    py = (pad + frame_t) + (avail_h - new_h) // 2

    wall = make_background(w, h)
    wall = _wall_light(wall, px + new_w // 2, py, int(new_w * 1.15))
    canvas = wall.convert("RGBA")

    # Sombra de contacto: corta y pegada al marco, como una obra bien colgada.
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle(
        [px - frame_t, py - frame_t + int(frame_t * 0.8),
         px + new_w + frame_t, py + new_h + frame_t + int(frame_t * 1.4)],
        fill=(0, 0, 0, 74))
    sh = sh.filter(ImageFilter.GaussianBlur(radius=max(2, int(frame_t * 1.5))))
    canvas = Image.alpha_composite(canvas, sh)

    canvas = canvas.convert("RGB")
    draw_frame(canvas, px, py, new_w, new_h, frame_t)
    canvas.paste(painting, (px, py))

    # Cartela: centrada verticalmente contra la obra, para que las dos lean como una
    # sola banda horizontal y el vacío se reparta arriba y abajo (no se acumule debajo).
    label_x = w - pad - col_w
    label_y = py + (new_h - label.height) // 2
    label_y = max(pad, min(label_y, h - pad - label.height))
    canvas = canvas.convert("RGBA")
    canvas.alpha_composite(label, (int(label_x), int(label_y)))
    return canvas.convert("RGB")


# ---------------------------------------------------------------------------
# Wallpaper (macOS)
# ---------------------------------------------------------------------------
def _macos_major() -> int:
    try:
        out = subprocess.run(["sw_vers", "-productVersion"], capture_output=True,
                             text=True, timeout=5).stdout
        return int(out.strip().split(".")[0])
    except Exception:  # noqa: BLE001
        return 0


def set_wallpaper(path: Path) -> None:
    """Fija el fondo en TODOS los monitores y escritorios/Spaces."""
    p = str(path)
    # 1) AppleScript: todos los monitores (y, en macOS reciente, todos los Spaces).
    script = ('tell application "System Events" to tell every desktop '
              f'to set picture to POSIX file "{p}"')
    try:
        subprocess.run(["osascript", "-e", script], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[aviso] No se pudo fijar el wallpaper: {e}\n        Imagen: {p}", file=sys.stderr)

    # 2) macOS <= Monterey (12): la BD del Dock fija TODOS los Spaces de una vez.
    major = _macos_major()
    db = Path.home() / "Library/Application Support/Dock/desktoppicture.db"
    if major and major <= 12 and db.exists():
        try:
            subprocess.run(["sqlite3", str(db), f"UPDATE data SET value = '{p}'"], check=True)
            subprocess.run(["killall", "Dock"], check=False)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass


def prune_outputs(keep: int = 4) -> None:
    if not OUT_DIR.exists():
        return
    files = sorted(OUT_DIR.glob("wall-*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_once(forced_id: str | None) -> None:
    catalog = load_catalog()
    catalog_size = len(catalog)          # --id filtra el catálogo; la ventana no debe encogerse
    if forced_id:
        catalog = [a for a in catalog if a["id"] == forced_id] or sys.exit(
            f"No existe una obra con id '{forced_id}'.")

    state = read_state()
    exclude = set(state.get("recent", []))
    tried: set = set()

    for attempt in range(MAX_ATTEMPTS):
        art = pick_artwork(catalog, exclude | tried)
        try:
            meta = resolve_meta(art)
            img_path = fetch_image(art, meta.get("image_url"))
            try:
                meta["artist_img"] = get_artist_image(art, meta)  # foto del artista (opcional)
            except Exception:  # noqa: BLE001 — la placa funciona sin foto
                meta["artist_img"] = None
            w, h = screen_size()
            wall = compose(meta, img_path, w, h)
        except Exception as e:  # noqa: BLE001 — probamos otra obra
            print(f"[skip] {art['id']}: {e}", file=sys.stderr)
            tried.add(art["id"])
            continue

        print(f"Obra: {meta.get('title')} — {meta.get('artist')} ({meta.get('year')})")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"wall-{time.strftime('%Y%m%d-%H%M%S')}-{art['id']}.jpg"
        wall.save(out, "JPEG", quality=95)
        prune_outputs()
        prune_cache()
        set_wallpaper(out)
        keep = recent_window(catalog_size)
        write_state({"recent": ([art["id"]] + state.get("recent", []))[:keep]})
        print(f"Listo: {out}")
        return

    sys.exit(f"No se pudo componer ninguna obra tras {MAX_ATTEMPTS} intentos (¿sin red?).")


def selftest() -> None:
    out_dir = HERE / "_preview"
    out_dir.mkdir(exist_ok=True)
    w, h = 2560, 1440
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def synth(pw, ph, colors):
        im = Image.new("RGB", (pw, ph))
        px = im.load()
        for y in range(ph):
            t = y / ph
            c = tuple(int(colors[0][i] * (1 - t) + colors[1][i] * t) for i in range(3))
            for x in range(pw):
                px[x, y] = c
        return im

    cat = {a["id"]: a for a in load_catalog()}
    p1 = CACHE_DIR / "_synth_land.img"
    synth(1524, 840, [(30, 40, 70), (90, 60, 40)]).save(p1, "JPEG")
    m1 = resolve_meta(cat["nighthawks"]) if "nighthawks" in cat else \
        {"title": "Nighthawks", "artist": "Edward Hopper", "year": "1942",
         "medium": "Óleo sobre lienzo", "size": "84,1 × 152,4 cm",
         "place": "Art Institute of Chicago", "note": "Prueba."}
    compose(m1, p1, w, h).save(out_dir / "preview-horizontal.jpg", "JPEG", quality=92)

    p2 = CACHE_DIR / "_synth_port.img"
    synth(700, 900, [(60, 45, 35), (20, 18, 22)]).save(p2, "JPEG")
    m2 = resolve_meta(cat["pearl-earring"]) if "pearl-earring" in cat else \
        {"title": "La joven de la perla", "artist": "Johannes Vermeer", "year": "c. 1665",
         "medium": "Óleo sobre lienzo", "size": "44,5 × 39 cm",
         "place": "Mauritshuis, La Haya", "note": "Prueba."}
    compose(m2, p2, w, h).save(out_dir / "preview-vertical.jpg", "JPEG", quality=92)
    print(f"Previews en: {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Rotador de fondo con arte + ficha técnica")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--id")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--compact", action="store_true",
                    help="reduce el caché ya existente y aplica el techo de tamaño")
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)
    if args.compact:
        compact_cache()
    elif args.selftest:
        selftest()
    else:
        run_once(args.id)


if __name__ == "__main__":
    main()
