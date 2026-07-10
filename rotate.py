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
RECENT_MEMORY = 12                # cuántas obras recientes evitar repetir
FAV_WEIGHT = 4                    # peso de una obra favorita frente a 1 de una normal
MAX_ATTEMPTS = 8                  # obras a intentar antes de rendirse en una rotación

# Estética — pared de galería (luz cálida tipo museo NY/Londres)
WALL_TOP = (206, 198, 185)      # greige cálido, algo más claro arriba
WALL_BOT = (176, 167, 153)      # más apagado hacia el suelo
WALL_WARM = (248, 243, 232)     # color del haz de luz que ilumina el cuadro
GOLD = (198, 168, 109)          # dorado (hilo de la placa)
FRAME_GOLD = (196, 162, 96)     # marco dorado base
FRAME_HI = (232, 210, 156)      # brillo del bisel
FRAME_LO = (120, 92, 46)        # sombra del bisel / rebaje
PAINTING_PAD = 0.058


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


def _get_json(url: str, timeout: int = 25):
    try:
        out = subprocess.run(
            ["curl", "-sSL", "--fail", "--max-time", str(timeout), "-A", USER_AGENT, url],
            check=True, capture_output=True, text=True,
        ).stdout
        return json.loads(out)
    except (subprocess.CalledProcessError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Fuentes (macOS primero, DejaVu como fallback para pruebas)
# ---------------------------------------------------------------------------
FONT_CANDIDATES = {
    "serif_bold": ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
                   "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"],
    "serif": ["/System/Library/Fonts/Supplemental/Georgia.ttf",
              "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
    "serif_italic": ["/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
                     "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"],
    "sans": ["/System/Library/Fonts/Supplemental/Arial.ttf",
             "/System/Library/Fonts/Helvetica.ttc",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "sans_bold": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
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
    for path in FONT_CANDIDATES[kind]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
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


def pick_artwork(catalog: list, exclude: set):
    import random
    pool = [a for a in catalog if a["id"] not in exclude] or catalog
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
    dims = ""
    if val("height") and val("width"):
        dims = f"{_fmt_dim(val('height'))} × {_fmt_dim(val('width'))} cm"
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
            if art.get("note"):
                meta["note"] = art["note"]
            return meta
        except ValueError:
            pass

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
    cache.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


def get_artist_image(art: dict, meta: dict) -> Path | None:
    """Foto/retrato del artista desde Wikidata (creador P170 → imagen P18). Cacheada por
    artista. Devuelve None si no se encuentra o no hay red (la placa simplemente lo omite)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (meta.get("artist") or "").lower()).strip("-")
    if not slug:
        return None
    cached = META_DIR / f"artist-{slug}.img"
    if cached.exists() and cached.stat().st_size > 512:
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
    return cached if _curl(url, cached) else None


# ---------------------------------------------------------------------------
# Descarga de la imagen (resolución ORIGINAL)
# ---------------------------------------------------------------------------
def fetch_image(art: dict, image_url_hint: str | None) -> Path:
    cached = CACHE_DIR / f"{art['id']}.img"
    if cached.exists() and cached.stat().st_size > 512:
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
        if _curl(u, cached):
            return cached
    raise RuntimeError(f"No se pudo descargar la imagen de '{art['id']}'.")


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
    """Pared de galería: greige cálido con gradiente vertical y una textura de pared fina."""
    top = Image.new("RGB", (w, h), WALL_TOP)
    bot = Image.new("RGB", (w, h), WALL_BOT)
    m = Image.new("L", (1, h))
    for y in range(h):
        m.putpixel((0, y), int(255 * (y / h)))
    wall = Image.composite(bot, top, m.resize((w, h)))
    # textura de pared muy sutil (para que no se vea plano/digital)
    noise = Image.effect_noise((w, h), 14).convert("RGB")
    wall = Image.blend(wall, noise, 0.045)
    return wall


def _light_pool(wall: Image.Image, cx: int, cy: int, rx: int, ry: int) -> Image.Image:
    """Simula el haz cálido de un foco de museo centrado en el cuadro; oscurece bordes."""
    w, h = wall.size
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=min(w, h) // 5))
    warm = Image.new("RGB", (w, h), WALL_WARM)
    wall = Image.composite(warm, wall, glow.point(lambda v: int(v * 0.5)))
    # leve caída de luz en las esquinas
    vig = Image.new("L", (w, h), 0)
    ImageDraw.Draw(vig).ellipse([-w * 0.15, -h * 0.15, w * 1.15, h * 1.15], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(radius=min(w, h) // 5))
    dark = Image.blend(wall, Image.new("RGB", (w, h), (0, 0, 0)), 0.28)
    return Image.composite(wall, dark, vig)


def draw_frame(canvas: Image.Image, x: int, y: int, iw: int, ih: int, t: int) -> None:
    """Marco dorado con bisel sobre el lienzo en (x,y,iw,ih)."""
    d = ImageDraw.Draw(canvas)
    d.rectangle([x - t, y - t, x + iw + t - 1, y + ih + t - 1], fill=FRAME_GOLD)
    # brillo del bisel (arriba/izquierda) y sombra (abajo/derecha)
    hi = max(2, t // 4)
    d.line([x - t, y - t, x + iw + t - 1, y - t], fill=FRAME_HI, width=hi)
    d.line([x - t, y - t, x - t, y + ih + t - 1], fill=FRAME_HI, width=hi)
    d.line([x - t, y + ih + t - 1, x + iw + t - 1, y + ih + t - 1], fill=FRAME_LO, width=hi)
    d.line([x + iw + t - 1, y - t, x + iw + t - 1, y + ih + t - 1], fill=FRAME_LO, width=hi)
    # rebaje oscuro pegado al lienzo (da profundidad)
    d.rectangle([x - 2, y - 2, x + iw + 1, y + ih + 1], outline=FRAME_LO, width=max(2, t // 3))
    d.rectangle([x - 1, y - 1, x + iw, y + ih], outline=(30, 22, 10), width=2)


def rounded_panel(size, radius, fill, border=None, bw=2) -> Image.Image:
    w, h = size
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(panel)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=fill)
    if border:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, outline=border, width=bw)
    return panel


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
    ImageDraw.Draw(im).rectangle([0, 0, w - 1, h - 1], outline=(120, 110, 95))
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
    ImageDraw.Draw(out).ellipse([1, 1, d - 2, d - 2], outline=(150, 116, 52), width=max(2, d // 26))
    return out


def build_card(meta: dict, card_w: int, scale: float) -> Image.Image:
    """Cartela de museo: identidad de la obra + una nota legible sobre por qué importa.
    Sin rótulos meta ('ficha técnica', 'rotación'): solo la obra. Tolera campos ausentes."""
    pad = int(40 * scale)
    inner_w = card_w - 2 * pad

    f_title = load_font("serif_bold", int(52 * scale))
    f_orig = load_font("serif_italic", int(25 * scale))
    f_artist = load_font("serif", int(34 * scale))
    f_line = load_font("sans", int(26 * scale))          # año · país
    f_place = load_font("sans_bold", int(26 * scale))    # museo, ciudad
    f_tech = load_font("sans", int(22 * scale))          # técnica · medidas (discreto)
    f_note = load_font("serif_italic", int(31 * scale))  # la nota: GRANDE y legible

    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    title = meta.get("title") or "Obra sin título"
    title_lines = wrap_text(title, f_title, inner_w, probe)
    orig = meta.get("orig") or ""
    show_orig = bool(orig) and orig != title

    artist = meta.get("artist") or ""
    yc_line = " · ".join([b for b in (meta.get("year"), meta.get("country")) if b])
    place_line = meta.get("place") or ""
    tech_line = " · ".join([b for b in (meta.get("medium"), meta.get("size")) if b])

    def lh(font, k=1.3):
        asc, desc = font.getmetrics()
        return int((asc + desc) * k)

    gap_s, gap_m, gap_l = int(7 * scale), int(16 * scale), int(28 * scale)

    # Retrato del artista (foto) y bandera de nacionalidad. NO agrandan la placa:
    # el retrato ocupa exactamente el alto del bloque autor+año (a su izquierda).
    portrait = None
    ap = meta.get("artist_img")
    if ap:
        try:
            portrait = ap if isinstance(ap, Image.Image) else Image.open(ap)
        except Exception:  # noqa: BLE001
            portrait = None
    iso = country_code(meta.get("country"))
    fh = int(f_line.size * 0.82)
    flag = draw_flag(iso, int(fh * 1.5), fh) if iso else None

    block_h = (lh(f_artist) if artist else 0) + ((gap_s + lh(f_line)) if yc_line else 0)
    d_ph = block_h if (portrait is not None and block_h > 0) else 0
    gap_ph = int(18 * scale)
    x_text = pad + (d_ph + gap_ph if d_ph else 0)

    # nota: envuelve al ancho completo (va debajo del retrato)
    note_lines = wrap_text(meta["note"], f_note, inner_w, probe) if meta.get("note") else []

    y = pad
    for _ in title_lines:
        y += lh(f_title)
    if show_orig:
        y += gap_s + lh(f_orig)
    y += gap_l  # separador dorado
    if block_h:
        y += gap_m + block_h
    if place_line:
        y += gap_s + lh(f_place)
    if tech_line:
        y += gap_s + lh(f_tech)
    if note_lines:
        y += gap_l + gap_m
        for _ in note_lines:
            y += lh(f_note, 1.34)
    card_h = y + pad

    # Placa de museo: marfil cálido con texto oscuro (como una cartela real en la pared).
    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    card.alpha_composite(rounded_panel((card_w, card_h), int(14 * scale),
                                       fill=(243, 237, 224, 252), border=(206, 195, 173, 255),
                                       bw=max(1, int(1.5 * scale))))
    d = ImageDraw.Draw(card)
    bronze = (150, 116, 52)

    x, y = pad, pad
    for line in title_lines:
        d.text((x, y), line, font=f_title, fill=(38, 33, 28, 255))
        y += lh(f_title)
    if show_orig:
        y += gap_s
        d.text((x, y), orig, font=f_orig, fill=(128, 120, 106, 255))
        y += lh(f_orig)

    y += gap_l
    d.rectangle([x, y, x + int(78 * scale), y + max(2, int(3 * scale))], fill=bronze)

    if block_h:
        y += gap_m
        block_top = y
        if d_ph:
            card.alpha_composite(circle_portrait(portrait, d_ph), (x, block_top))
        if artist:
            d.text((x_text, y), artist, font=f_artist, fill=(52, 46, 39, 255))
            y += lh(f_artist)
        if yc_line:
            if artist:
                y += gap_s
            d.text((x_text, y), yc_line, font=f_line, fill=(98, 90, 78, 255))
            if flag is not None:
                fx = x_text + int(probe.textlength(yc_line, font=f_line)) + int(12 * scale)
                fy = y + (lh(f_line) - fh) // 2 - int(2 * scale)
                if fx + flag.width <= card_w - pad:
                    card.alpha_composite(flag, (fx, fy))
            y += lh(f_line)
        y = max(y, block_top + block_h)

    if place_line:
        y += gap_s
        d.text((x, y), place_line, font=f_place, fill=(bronze[0], bronze[1], bronze[2], 255))
        y += lh(f_place)
    if tech_line:
        y += gap_s
        d.text((x, y), tech_line, font=f_tech, fill=(140, 132, 120, 255))
        y += lh(f_tech)

    if note_lines:
        y += gap_l
        d.line([x, y, card_w - pad, y], fill=(206, 195, 176, 255), width=1)
        y += gap_m
        for line in note_lines:
            d.text((x, y), line, font=f_note, fill=(46, 41, 35, 255))
            y += lh(f_note, 1.34)
    return card


def compose(meta: dict, img_path: Path, w: int, h: int) -> Image.Image:
    """Como estar frente a la obra colgada en una pared de museo: cuadro enmarcado con
    foco cálido y sombra proyectada, y a su lado la placa (cartela) en la pared."""
    scale = h / 1800.0
    pad = int(min(w, h) * PAINTING_PAD)
    gap = int(pad * 0.9)
    frame_t = max(10, int(min(w, h) * 0.014))

    # Placa deliberadamente contenida: el cuadro es el protagonista, la placa es apoyo.
    card_w = int(min(max(w * 0.235, 540), 820))
    card = build_card(meta, card_w, scale)

    # La pintura vive a la IZQUIERDA de la columna de la placa (nunca se tocan).
    right_reserved = card_w + gap
    area_x0 = pad + frame_t
    area_x1 = w - pad - right_reserved
    avail_w = max(1, area_x1 - area_x0)
    avail_h = h - 2 * (pad + frame_t)

    painting = Image.open(img_path).convert("RGB")
    pw, ph = painting.size
    ratio = min(avail_w / pw, avail_h / ph)
    new_w, new_h = max(1, int(pw * ratio)), max(1, int(ph * ratio))
    painting = painting.resize((new_w, new_h), Image.LANCZOS)
    px = area_x0 + (avail_w - new_w) // 2
    py = (pad + frame_t) + (avail_h - new_h) // 2

    # Pared + haz de luz de museo centrado en el cuadro.
    wall = make_background(w, h)
    wall = _light_pool(wall, px + new_w // 2, py + int(new_h * 0.45),
                       int(new_w * 0.95), int(new_h * 0.9))
    canvas = wall.convert("RGBA")

    # Sombra proyectada del cuadro sobre la pared (colgado, luz desde arriba).
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle(
        [px - frame_t, py - frame_t + int(frame_t * 0.5),
         px + new_w + frame_t, py + new_h + frame_t + int(frame_t * 1.6)],
        fill=(0, 0, 0, 115))
    sh = sh.filter(ImageFilter.GaussianBlur(radius=int(frame_t * 1.3)))
    canvas = Image.alpha_composite(canvas, sh)

    canvas = canvas.convert("RGB")
    draw_frame(canvas, px, py, new_w, new_h, frame_t)
    canvas.paste(painting, (px, py))
    # re-dibuja el rebaje interior por encima del lienzo
    ImageDraw.Draw(canvas).rectangle([px - 1, py - 1, px + new_w, py + new_h],
                                     outline=(30, 22, 10), width=2)

    # Placa (cartela) en la pared, a la derecha, con su sombra.
    card_x = w - pad - card_w
    card_y = max(pad, (h - card.height) // 2)
    csh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(csh).rounded_rectangle(
        [card_x, card_y + int(6 * scale), card_x + card_w, card_y + card.height + int(12 * scale)],
        radius=int(14 * scale), fill=(0, 0, 0, 80))
    csh = csh.filter(ImageFilter.GaussianBlur(radius=int(13 * scale)))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), csh)
    canvas.alpha_composite(card, (int(card_x), int(card_y)))
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
        set_wallpaper(out)
        write_state({"recent": ([art["id"]] + state.get("recent", []))[:RECENT_MEMORY]})
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
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if args.selftest:
        selftest()
    else:
        run_once(args.id)


if __name__ == "__main__":
    main()
