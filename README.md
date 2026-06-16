---
title: EventScope
emoji: 📍
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
app_port: 7860
---

# EventScope

> Descubrí lo que pasa cerca, antes de que pase.

Agregador inteligente de eventos locales para la **Zona Sur del GBA** (piloto:
Adrogué / Partido de Almirante Brown, ~15km de radio) con pipeline de
normalización vía LLM, deduplicación y API geoespacial.

## Estado del MVP

| Componente | Estado |
|---|---|
| Esquema de datos (`raw_events`, `events`, `user_interactions`) | ✅ SQLAlchemy + DDL PostGIS |
| Framework de scrapers + registro | ✅ |
| **Almirante Brown** (WordPress REST API) | ✅ |
| **Lomas de Zamora** (agenda-de-la-comunidad) | ✅ |
| **Quilmes** (noticias culturales) | ✅ |
| Venue HTML (schema.org JSON-LD + CSS) | ✅ |
| Eventbrite (API oficial) | ✅ |
| Instagram oEmbed (enriquecimiento) | ✅ resolver inyectable |
| Extracción LLM (stub + Gemini + OpenAI) | ✅ provider-agnóstico |
| Deduplicación (embeddings + fecha/geo) | ✅ stub offline |
| Geocoding (Nominatim / NullGeocoder) | ✅ hook inyectable |
| Pipeline end-to-end | ✅ |
| CLI completo (ingest / enrich / purge / status) | ✅ |
| API FastAPI (nearby / range / detail / admin) | ✅ |
| Purge automático de eventos vencidos | ✅ |
| App cliente (SwiftUI vs Flutter) | ⏳ Fase 2 — decisión diferida |

## Quickstart (offline)

```bash
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"   # Windows

pytest                    # 39+ tests, 0 credenciales, 0 red
eventscope init-db        # crear tablas (SQLite por defecto)
eventscope scrapers       # listar fuentes registradas
eventscope serve --port 8080
# → http://127.0.0.1:8080/docs
```

## Correr el pipeline real

```bash
# Copiar config y agregar credenciales opcionales
cp .env.example .env

# Ingestar todos los scrapers discovery (sin credenciales: brown, lomas, quilmes)
eventscope ingest

# Un scraper específico
eventscope ingest --source lomas_agenda

# Probar sin escribir a DB
eventscope ingest --dry-run

# Resolver permalinks de Instagram cosechados (requiere IG_ACCESS_TOKEN)
eventscope enrich

# Cancelar eventos vencidos
eventscope purge --days 7

# Ver estadísticas
eventscope status
```

## Arquitectura del pipeline

```
ScrapedItem(s)
  → raw_events            (landing inmutable, idempotente por source+external_id)
  → extracción LLM        (campos normalizados)
  → validación            (título + fecha futura)
  → dedup clustering      (embeddings + similitud coseno + fecha/geo)
  → events (normalizado)  → API REST → Mapa / Calendario / Agenda
```

**Geocoding (limitación conocida Fase 1):** fuentes sin coordenadas propias
(gobierno, Instagram) pasan por el hook `Geocoder`. Por defecto es no-op.
Eventos sin coords aparecen en `/events/range` pero no en `/events/nearby`.
Activar con `EVENTSCOPE_GEOCODER_PROVIDER=nominatim`.

## Fuentes de datos

| Fuente | Tipo | URL |
|---|---|---|
| **Almirante Brown** | Discovery (WP REST API) | `brown.gob.ar/wp-json/...` |
| **Lomas de Zamora** | Discovery (HTML) | `lomasdezamora.gov.ar/agenda-de-la-comunidad` |
| **Quilmes** | Discovery (HTML) | `quilmes.gov.ar/noticias/?categoria=cultura` |
| **Venue HTML** | Discovery (JSON-LD) | Configurable por venue |
| **Eventbrite** | Discovery (API) | API oficial |
| **Instagram oEmbed** | **Enriquecimiento** | Meta Graph API v19 |

### Instagram — enriquecimiento, no discovery

oEmbed **no puede descubrir ni listar** posts de un perfil; solo resuelve un
permalink conocido. Los scrapers cosechan links de IG de las páginas que
scrapeean y los guardan en `raw_events.payload["instagram_permalinks"]`.
`eventscope enrich` los resuelve vía oEmbed en una segunda pasada. Es
idempotente: saltea permalinks ya resueltos.

Desde **abril 2025** el endpoint sin autenticar fue removido. Se necesita token
de app Meta con `oembed_read`. Sin token: fallback a iframe embed público.

## API endpoints

```
GET /health
GET /events/nearby?lat=&lng=&radius_km=5&category=musica&free_only=false
GET /events/range?start=2026-06-15T00:00:00Z&end=2026-06-22T00:00:00Z
GET /events/{id}
GET /admin/status
```

## Configuración de producción

```bash
# Levantar Postgres + PostGIS
docker compose up -d db

# .env mínimo para producción
EVENTSCOPE_DATABASE_URL=postgresql+psycopg://eventscope:eventscope@localhost:5432/eventscope
EVENTSCOPE_LLM_PROVIDER=gemini
EVENTSCOPE_LLM_API_KEY=AIza...
EVENTSCOPE_GEOCODER_PROVIDER=nominatim
```

Ver `.env.example` para todas las opciones.

## Layout

```
src/eventscope/
  config.py          settings (env, todo OFF por defecto)
  models.py  db.py   ORM + sesión
  geo.py  repository.py
  scrapers/          base + registro + 7 fuentes
  extraction/        schema + extractor (stub/Gemini/OpenAI)
  dedup/             embeddings + deduplicador
  geocoding.py       Geocoder ABC (Null / Static / Nominatim)
  pipeline.py        run_items() + enrich_from_instagram() + purge_stale_events()
  api/               FastAPI (nearby / range / detail / admin/status)
  cli.py             ingest / enrich / purge / status / serve
airflow/dags/        DAG de ejemplo (Airflow opcional)
db/schema.sql        DDL PostGIS (producción)
tests/               fixtures + suite offline
CLAUDE.md            contexto para sesiones de Claude Code
```
