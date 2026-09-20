# Roadmap — ideas para iterar

Lista viva de mejoras. No hay orden estricto; toma la que te apetezca. Marca con ✅ al terminar.

## Contenido
- [ ] Ampliar el catálogo (v1.1 lo llevó a 196 obras; siguen pendientes arte islámico,
      arte africano y precolombino, y más contemporáneo).
- [ ] Notas "por qué es célebre" para las obras que aún salgan de Wikidata sin nota propia.
- [ ] Colecciones temáticas seleccionables (impresionismo, retrato, paisaje, un solo museo).

## Ficha / cartela
- [ ] Modo "solo fotografía real" para el retrato del artista (saltar autorretratos pintados).
- [ ] Enlace/QR a la ficha del museo o a Wikipedia de la obra.
- [ ] Fuente configurable (serif clásica vs moderna) y tema de pared (greige / sage / burdeos / gris).

## Comportamiento
- [ ] Intervalo configurable desde un archivo `config.json` (en vez de editar el plist).
- [ ] Menu bar app (rumps) con "siguiente / anterior / fijar esta / abrir en el navegador".
- [x] "No repetir en N días" — hecho en v1.1: la ventana es el 60% del catálogo (~2,5 días).
- [ ] Respetar modo oscuro/claro del sistema para el tono de la pared.

## Robustez
- [ ] Forzar wallpaper por Space en macOS reciente si algún Space no se actualiza.
- [ ] Prefetch en segundo plano de la siguiente obra para cambios instantáneos.
- [ ] Tests: un `--selftest` que valide que cada `id` compone sin excepción (con imágenes dummy).

## Distribución
- [ ] Empaquetar como `.app` o Homebrew tap para instalar sin terminal.
- [ ] GIF/README con capturas de las mejores obras.
