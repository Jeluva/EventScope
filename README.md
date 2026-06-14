# EventScope

> Descubrí lo que pasa cerca, antes de que pase.

Agregador inteligente de eventos locales por **scraping multi-fuente**, con
pipeline de normalización vía LLM, deduplicación y una API geoespacial que
alimenta las vistas de Mapa, Calendario y Agenda.

Este repositorio implementa el **backend vertical slice** (Fase 0/1 del
documento de producto): el pipeline de ingestión + la API. Es el núcleo donde
vive el valor diferencial (curación + normalización), y corre **100% offline,
sin credenciales**, bajo `pytest`.

## Estado

| Componente | Estado |
|---|---|
| Esquema de datos (`raw_events`, `events`, `user_interactions`) | ✅ SQLAlchemy + DDL PostGIS |
| Framework de scrapers + registro | ✅ |
| Scrapers: Eventbrite, Venue HTML, Gobierno/Municipal, Instagram oEmbed | ✅ (fixture-tested) |
| Loop de enriquecimiento Instagram (harvest → resolve) | ✅ resolver inyectable |
| Extracción estructurada vía LLM | ✅ provider-agnóstico + stub offline |
| Deduplicación (embeddings + fecha/geo) | ✅ stub offline |
| Geocoding | ⚙️ hook inyectable, no-op por defecto |
| Pipeline end-to-end | ✅ |
| API FastAPI (nearby / range / detail) | ✅ |
| DAG de Airflow de ejemplo | ✅ (Airflow opcional) |
| App cliente (SwiftUI vs Flutter) | ⏳ Fase 2 — decisión diferida |

## Arquitectura del pipeline

```
ScrapedItem(s)
  → raw_events            (landing inmutable, idempotente por source+external_id)
  → extracción LLM        (campos normalizados, JSON-Schema)
  → validación            (título + fecha futura)
  → dedup clustering      (embeddings + similitud coseno + fecha/geo)
  → events (normalizado)  → API REST → Mapa / Calendario / Agenda
```

La **procedencia es de primera clase**: cada evento guarda `source` + `source_url`
(la app muestra de dónde salió el dato) y `last_verified_at` (mitigación de
eventos desactualizados).

**Geocoding (limitación conocida de Fase 1):** el pipeline usa eventos con
`lat`/`lng` provistos por la fuente (Eventbrite, JSON-LD de venues). Las fuentes
sin coordenadas (gobierno, Instagram) pasan por un hook `Geocoder` inyectable;
por defecto es *no-op* (no inventamos una ubicación). Hasta geocodificar, esos
eventos aparecen en el **Calendario** (`/events/range`) pero **no en el Mapa**
(`/events/nearby` filtra por coordenadas). Conectá un `Geocoder` real
(Nominatim/Mapbox) para que sean visibles en el mapa.

## Fuentes de datos

| Fuente | Tipo | Notas |
|---|---|---|
| **Eventbrite** | Discovery (API oficial) | Fuente primaria, bajo riesgo. |
| **Venue HTML** | Discovery (JSON-LD / selectores) | Lee schema.org `Event`; además cosecha permalinks de Instagram. |
| **Gobierno / Municipal** | Discovery (selectores) | **Nuevo** — agenda cultural municipal, público y estable. |
| **Instagram oEmbed** | **Enriquecimiento** | Ver abajo. |

### Instagram — por qué es enriquecimiento, no discovery

oEmbed **no puede descubrir ni listar** los posts de un perfil; sólo resuelve un
*permalink* conocido a embed + caption + thumbnail + autor. Por eso Instagram se
modela como un paso de **enriquecimiento** sobre permalinks que vienen de (a) una
lista semilla manual y (b) links cosechados por los scrapers de venues/gobierno.

El loop está implementado en `pipeline.enrich_from_instagram()`: corre como
segunda pasada, lee los permalinks cosechados (guardados en `raw_events.payload`)
+ una lista semilla, los resuelve vía un `resolver` inyectable (oEmbed real en
producción, fake en tests) y los ingesta por el mismo pipeline. Es idempotente:
saltea los permalinks ya resueltos.

Desde **abril 2025** el endpoint oEmbed sin autenticar fue removido: el endpoint
Graph API *oEmbed Read* requiere un access token de app Meta con `oembed_read`.
Cuando no hay token, EventScope degrada con elegancia al embed iframe público
(`/p/{shortcode}/embed/`). Todo configurable; los tests no usan red ni token.

## Quickstart (offline)

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"   # Windows; usar bin/ en Linux/Mac

pytest                                   # 27 tests, 0 credenciales, 0 red
eventscope scrapers                      # lista los scrapers registrados
eventscope init-db                       # crea las tablas (SQLite por defecto)
eventscope serve                         # API dev en http://127.0.0.1:8000/docs
```

### Endpoints

- `GET /events/nearby?lat=&lng=&radius_km=&category=&free_only=` — Mapa
- `GET /events/range?start=&end=&category=` — Calendario
- `GET /events/{id}` — detalle

## Producción

- **DB**: `docker compose up -d db` levanta Postgres + PostGIS y aplica
  `db/schema.sql`. Apuntá `EVENTSCOPE_DATABASE_URL` al servicio.
- **LLM**: poné `EVENTSCOPE_LLM_PROVIDER=gemini|openai` + `EVENTSCOPE_LLM_API_KEY`.
- **Embeddings**: `EVENTSCOPE_EMBEDDING_PROVIDER=sentence-transformers`
  (`pip install -e ".[embeddings]"`).
- **Orquestación**: un DAG de Airflow por fuente (ver `airflow/dags/`).

Copiá `.env.example` a `.env`. Toda integración viva está **apagada por defecto**.

## Layout

```
src/eventscope/
  config.py            settings (env, todo OFF por defecto)
  models.py  db.py     ORM + sesión
  geo.py  repository.py  haversine/bbox + queries por radio/fecha
  scrapers/            base + registro + 4 fuentes
  extraction/          schema + extractor (stub/LLM)
  dedup/               embeddings + deduplicador
  geocoding.py         hook Geocoder (null por defecto, inyectable)
  pipeline.py          orquestación end-to-end + enrich_from_instagram()
  api/                 FastAPI
  cli.py
airflow/dags/          DAG de ejemplo (Airflow opcional)
db/schema.sql          DDL PostGIS (producción)
tests/                 fixtures + suite offline
```
