# Changelog

Historial del proyecto (lo más reciente arriba). Fechas aproximadas.

## v1.2 — 2026-09
Rediseño visual: de museo decimonónico a sala contemporánea.

- **Pared**: blanca plana con grano al 2%. Fuera el degradado greige, el foco cálido radial y la
  viñeta de esquinas — eran lo que hacía que el conjunto pareciera un fondo de Windows 95.
  `_light_pool` se sustituye por `_wall_light`, un lavado cenital del 4% sin viñeta.
- **Marco**: banda negra fina y plana (0,55% del lado corto, antes 1,4%) con una única línea de luz
  en el canto superior. Fuera el dorado, el bisel y el rebaje. La profundidad la da una sombra de
  contacto corta y pegada al marco.
- **Cartela**: ya no es una tarjeta marfil redondeada con sombra, sino texto impreso directamente
  en la pared (`build_label`), alineado a la izquierda y centrado verticalmente contra la obra.
- **Tipografía**: Helvetica Neue para todo, cargada por índice dentro del `.ttc` (Light, Medium,
  Italic). La jerarquía la dan cuerpo y gris, no la mezcla serif/sans ni el hilo dorado.
- **Sala oscura** disponible con `DARK_ROOM = True`.
- El título en español ya no repite el original cuando lo contiene entre paréntesis.
- **Medidas en metros**: Wikidata daba el Políptico de Gante como "3,4 × 5,2 cm"; ahora se
  convierten. Y "apátrida" deja de aparecer como país.

## v1.1 — 2026-09
Caché con techo y catálogo casi al doble.

- **El caché ya no crece sin límite.** Las imágenes se guardan acotadas a 2.200 px de lado
  (`ART_MAX_SIDE`) y los retratos de artista a 420 px, en JPEG. En cada rotación se aplica un
  techo de 250 MB (`prune_cache`) borrando las menos usadas; `fetch_image` marca cada reutilización
  con `os.utime` para que el criterio sea uso real y no fecha de descarga.
  Medido en la máquina de origen: **717 MB → 84 MB**, sin diferencia visible en pantalla.
- **Se descarga ya reducido.** `_thumb_url` reescribe la URL de Wikimedia a su miniatura del ancho
  necesario; evita bajar TIFFs de 80 MB (un retrato de Rembrandt pesaba eso). Con *fallback* al
  original si la miniatura no existe.
- **`--compact`**: pasada única que reduce y poda el caché ya guardado.
- **Menos repetición.** La ventana de no-repetición pasa de 12 obras fijas al 60% del catálogo
  (`recent_window`) y el peso de las favoritas de ×4 a ×2. Con 184 obras en rotación, el intervalo mínimo
  entre repeticiones sube de **6 h a 59 h** (simulado sobre 480 rotaciones).
- **Catálogo: 100 → 195 obras.** 96 entradas nuevas, cada una con su nota de por qué es célebre,
  verificadas contra Wikipedia (existe el artículo y tiene imagen de ≥1.400 px). Amplía a
  Artemisia Gentileschi, Cassatt, Morisot, Bonheur, Repin, Aivazovsky, Munch, Hiroshige, Utamaro,
  Eakins, Homer, Sargent, Church, Caillebotte, Tarsila do Amaral, Rivera, Malevich y Schiele,
  entre otros.
- **Imágenes corruptas en caché se descartan solas** en vez de romper la obra para siempre.

### Correcciones de catálogo (auditoría de las 195 entradas)
- **Una consulta fallida a Wikidata se cacheaba para siempre.** 12 de 95 fichas guardadas estaban
  sin autor, año ni museo desde v1.0. Ahora `_get_json` reintenta con espera y `resolve_meta` sólo
  cachea fichas con autor; una ficha vacía guardada se vuelve a resolver sola.
- **Cinco entradas apuntaban al artículo equivocado de Wikipedia** y enmarcaban la imagen de ese
  artículo: `Mont_Sainte-Victoire` (la montaña), `Gare_Saint-Lazare` (la estación),
  `Rain,_Steam_and_Speed` (un disco de 1999), `The_Lamentation_of_Christ` y `The_Wedding_at_Cana`
  (los temas bíblicos, no los cuadros). Corregidas con el sufijo del autor.
- **`Nighthawks` y `Ophelia` eran páginas de desambiguación**: dos favoritas que no llegaban a
  salir nunca. Ahora `Nighthawks_(Hopper)` (6000 px) y `Ophelia_(Millais)` (7087 px).
- **Obras del siglo XX sin imagen utilizable**: de Guernica, La persistencia de la memoria, Las dos
  Fridas o El mundo de Christina, Wikipedia sólo ofrece una imagen de uso legítimo de 300-500 px,
  que enmarcada se ve pixelada. Se marcan con `"skip"` (siguen en el catálogo, fuera de la
  rotación) y `MIN_ART_SIDE` impide que cualquier imagen menor de 1.000 px llegue a la pantalla.
- Catálogo: **195 obras, 184 en rotación**.

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
