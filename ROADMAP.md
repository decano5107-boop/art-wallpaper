# Roadmap — ideas para iterar

Lista viva de mejoras. No hay orden estricto; toma la que te apetezca. Marca con ✅ al terminar.

## Contenido
- [ ] Ampliar el catálogo (arte no occidental: ukiyo-e más allá de Hokusai, arte islámico,
      muralismo mexicano, arte africano y precolombino, contemporáneo).
- [ ] Notas "por qué es célebre" para las obras que aún salgan de Wikidata sin nota propia.
- [ ] Colecciones temáticas seleccionables (impresionismo, retrato, paisaje, un solo museo).

## Ficha / cartela
- [ ] Modo "solo fotografía real" para el retrato del artista (saltar autorretratos pintados).
- [ ] Enlace/QR a la ficha del museo o a Wikipedia de la obra.
- [ ] Fuente configurable (serif clásica vs moderna) y tema de pared (greige / sage / burdeos / gris).

## Comportamiento
- [ ] Intervalo configurable desde un archivo `config.json` (en vez de editar el plist).
- [ ] Menu bar app (rumps) con "siguiente / anterior / fijar esta / abrir en el navegador".
- [ ] "No repetir en N días" en vez de solo las últimas 12.
- [ ] Respetar modo oscuro/claro del sistema para el tono de la pared.

## Robustez
- [ ] Forzar wallpaper por Space en macOS reciente si algún Space no se actualiza.
- [ ] Prefetch en segundo plano de la siguiente obra para cambios instantáneos.
- [ ] Tests: un `--selftest` que valide que cada `id` compone sin excepción (con imágenes dummy).

## Distribución
- [ ] Empaquetar como `.app` o Homebrew tap para instalar sin terminal.
- [ ] GIF/README con capturas de las mejores obras.
