# Changelog

Historial del proyecto (lo más reciente arriba). Fechas aproximadas.

## v1.0 — 2026-07
Primera versión completa y en uso.

- **Motor** (`rotate.py`): selección ponderada, descarga a resolución original con caché,
  composición con Pillow y fijado del fondo. Reintenta con otra obra si una falla.
- **Catálogo** (`artworks.json`): 100 obras. 25 curadas (incluidas las 25 de un video de "obras
  más famosas") + 75 de descubrimiento resueltas por Wikidata. Favoritas ×4.
- **Estética de museo**: pared cálida con textura + foco de luz + viñeta; cuadro con marco dorado
  y sombra proyectada (colgado en la pared).
- **Cartela**: placa marfil con nombre, autor (**foto** desde Wikidata), año, **país + bandera
  dibujada**, museo, ciudad, técnica/medidas y una **nota de por qué la obra es célebre**.
- **Notas curadas** para las 100 obras (en vez del extracto seco de Wikipedia).
- **Wallpaper en todos los monitores/Spaces**.
- **Instalación**: venv aislado + LaunchAgent (cada 30 min). Compatible con el bash 3.2 de macOS.

### Hitos del camino (para contexto)
fondo oscuro → intervalo 30 min → catálogo abierto (Wikidata) → favoritas del video →
rediseño cartela de museo (lado a lado) → pared de galería con luz → foto del artista + bandera →
notas de "por qué es famosa" → todos los Spaces.
