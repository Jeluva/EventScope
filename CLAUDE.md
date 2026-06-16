# EventScope — contexto para Claude Code

Sos un senior backend engineer argentino desarrollando **EventScope**: un
agregador inteligente de eventos locales para la Zona Sur del GBA
(piloto: Adrogué / Partido de Almirante Brown, radio 15km).

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 (SQLite dev / PostGIS prod)  
pydantic-settings · pytest (offline, cero credenciales) · Airflow (opcional)

## Pipeline

```
ScrapedItem → raw_events (inmutable) → LLM extract → validar → dedup cluster
→ events → FastAPI (/events/nearby · /events/range · /events/{id} · /admin/status)
```

## Scrapers registrados

| Nombre           | Tipo          | Fuente                                        |
|------------------|---------------|-----------------------------------------------|
| `eventbrite`     | discovery     | Eventbrite API                                |
| `venue_html`     | discovery     | Venues con schema.org JSON-LD + CSS selectors |
| `government`     | discovery     | Municipal genérico (selector configurable)    |
| `almirante_brown`| discovery     | brown.gob.ar — WordPress REST API             |
| `lomas_agenda`   | discovery     | lomasdezamora.gov.ar/agenda-de-la-comunidad   |
| `quilmes`        | discovery     | quilmes.gov.ar/noticias/?categoria=cultura    |
| `instagram_oembed`| enrichment   | Meta oEmbed Read (no es discovery)            |

## Instagram — regla de oro

Instagram es **enriquecimiento, no discovery**. oEmbed solo resuelve
permalinks conocidos. El flujo:
1. scrapers de venues/gobierno cosechan links IG → `raw_events.payload["instagram_permalinks"]`
2. `eventscope enrich` → `pipeline.enrich_from_instagram()` los resuelve

Desde **abril 2025** el endpoint sin auth fue removido. Necesita token Meta
con `oembed_read`. Sin token: fallback a iframe embed. **Nunca intentar
listar/monitorear perfiles ajenos.**

## CLI disponible

```bash
eventscope init-db              # crear tablas
eventscope scrapers             # listar fuentes registradas
eventscope ingest               # correr todos los scrapers discovery
eventscope ingest --source lomas_agenda  # uno específico
eventscope ingest --dry-run     # sin escribir a la DB
eventscope enrich               # resolver permalinks IG cosechados
eventscope enrich --seed URL    # + permalink manual
eventscope purge                # cancelar eventos > 7 días en el pasado
eventscope purge --days 14 --dry-run
eventscope status               # estadísticas de la DB
eventscope serve --port 8080    # API dev
```

## Convenciones

- Todo config via env vars prefijo `EVENTSCOPE_`, todo OFF por defecto
- `parse()` es puro (acepta str/bytes) — fixture-testable, cero red
- `fetch()` hace la red — separado de `parse()`
- `Geocoder` es inyectable; `NullGeocoder` por defecto (no inventar coords)
- Eventos sin coords aparecen en `/events/range` pero NO en `/events/nearby`
- `CATEGORIES = ("musica","arte","gastronomia","tech","networking","bienestar","ferias","otros")`
- Tests: SQLite in-memory, monkeypatch env, cero credenciales, cero red

## Geocoding (limitación conocida Fase 1)

Fuentes con coords propias: Eventbrite, JSON-LD venues.  
Fuentes sin coords (gobierno, Instagram): pasan por `Geocoder` hook.  
Por defecto es no-op. Activar Nominatim: `EVENTSCOPE_GEOCODER_PROVIDER=nominatim`.

## Fase 2 (pendiente)

- App mobile (SwiftUI native vs Flutter — decisión diferida)
- Motor de recomendaciones (`user_interactions`)
- Notificaciones push
- Embeddings reales (sentence-transformers) para dedup de calidad
