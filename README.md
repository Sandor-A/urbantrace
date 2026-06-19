# Urbantrace

## Overview

Urbantrace is an AI-powered research assistant for Cluj-Napoca real estate data. Users query structured property, transaction, and ownership records through natural language and get grounded, data-driven answers.

The core design principle:

> **The LLM plans and explains; deterministic Python tools execute.**

All filtering, aggregation, and joins happen in Python. The LLM never invents property records or calculates values directly. This makes the system auditable and hallucination-resistant.

---

## Key Features

- Natural-language property and ownership search
- Market statistics and trend analysis
- Tool/function-calling agent architecture
- Real neighborhood matching via OSM Nominatim geocoding (with local cache)
- Interactive web interface with three pages: property search, market stats, ownership
- Brick — an animated AI assistant widget embedded in every page
- Language switcher: English / Romanian / Hungarian (persisted to localStorage)
- Lightweight session memory for multi-turn follow-up queries
- CLI mode for direct terminal use

---

## Project Structure

```text
Urbantrace/
│
├── app.py                  # CLI entry point (REPL)
├── server.py               # FastAPI web server (routes + API endpoints)
├── agent.py                # Agent class — LLM loop, tool dispatch, session memory
├── tools.py                # Four callable tools with OpenAI-compatible JSON schemas
├── data_loader.py          # CSV ingestion, normalization, geocoder enrichment
├── geocoder.py             # Nominatim (OSM) geocoding with persistent cache
├── memory.py               # SessionMemory — tracks last tool, filters, results
│
├── static/
│   ├── index.html          # Property search page with Brick assistant widget
│   ├── stats.html          # Market statistics page with Chart.js charts
│   └── ownership.html      # Ownership search page with SRL/individual filters
│
├── data/
│   ├── properties.csv      # 500 property records
│   ├── transactions.csv    # Transaction/sales records (2018–2025)
│   ├── ownership.csv       # Ownership records (SRL vs individual)
│   ├── geocache.json       # Cached Nominatim geocoding results (auto-generated)
│   └── DATA_DICTIONARY.md  # Field definitions and schema notes
│
├── architecture/
│   └── AI_Search_Assistant_Architecture.md
│
├── testquestions.txt       # Manual QA queries
├── requirements.txt        # Python dependencies
├── CLAUDE.md               # Claude Code / AI development notes
└── README.md
```

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # add OPENAI_API_KEY
```

Override the model (default: `gpt-4o-mini`):

```
OPENAI_MODEL=gpt-4o-mini
```

**Run — web interface:**

```bash
python server.py
```

| URL | Page |
|---|---|
| `http://127.0.0.1:8000` | Property search |
| `http://127.0.0.1:8000/stats` | Market statistics dashboard |
| `http://127.0.0.1:8000/ownership` | Ownership search |

**Run — CLI:**

```bash
python app.py
```

---

## Web Interface

All three pages share a common design: glassmorphism sticky header with `backdrop-filter: blur`, Inter font, and the Brick assistant widget fixed in the bottom-right corner.

### Property Search (`/`)

- Hero search bar — keyword search across address, neighborhood, owner
- **Real-data example chips** — 4 address chips picked from diverse neighborhoods, sourced live from the database, pre-fill the search bar on click
- Filter chips — neighborhood dropdown (12 neighborhoods), ownership type (SRL / Individual / All), price range bands calibrated to actual RON distribution:
  - `< 500k RON` · `500k – 2M` · `2M – 10M` · `10M – 30M` · `> 30M RON`
- Property cards — SVG building illustrations, price, area (mp), price/mp, owner badge; 24 cards per page with **Load more** pagination
- **8 sort options**: Price high→low, Price low→high, Price/m² high→low, Price/m² low→high, Area large→small, Area small→large, Most recent sale, Oldest sale — sorting applies to the full filtered dataset and shows all results at once
- Filter bar **stays visible while scrolling** on mobile (sticky, z-index below the hamburger nav)
- Clicking a card pre-fills the Brick assistant with a question about that property

### Market Statistics (`/stats`)

Powered by the `/api/chart-data` endpoint which aggregates live from the CSV data.

**KPI cards:**

| Card | Value |
|---|---|
| Total Transactions | Count of arm's-length sales |
| Median Sale Price | Overall median across all valid transactions |
| Median RON/mp | Median price per square meter |
| Year-over-Year Change | % change in median price vs. prior year |

**Charts (Chart.js):**

| Chart | Type | Description |
|---|---|---|
| Price Trends | Multi-line | Median sale price per year — overall + top 5 neighborhoods |
| Transaction Volume | Bar | Number of sales per year |
| Neighborhood Comparison | Grouped bar | Median price vs. median RON/mp per neighborhood (dual Y-axis) |
| Ownership Structure | Doughnut | SRL (company) vs. individual owners |
| Price per sqm Trend | Area line | Overall median RON/mp over time |

### Ownership Search (`/ownership`)

Powered by the `/api/ownership-search` endpoint.

- Search bar — full-text search across address, owner name, and property key
- Tab filters — All / SRL / Individual
- Ownership cards — type icon, address, owner name, type badge, registration date, assessed value, "Ask Brick" shortcut
- Stats bar — total count / SRL count / individual count
- Load-more pagination (24 records per page)

### Language Switcher

All three pages include a `🇬🇧 EN / 🇷🇴 RO / 🇭🇺 HU` pill switcher in the header. The selected language is persisted to `localStorage('ut_lang')` and applied on page load via `data-i18n` attributes and a `TRANSLATIONS` object.

### Brick — AI Assistant Widget

A building-brick mascot fixed in the bottom-right corner of every page.

- **Hop animation** — squash-and-stretch jump triggered on card click, after 4 s idle, every 10 s
- **Chat panel** — slides up with a spring animation on click
- **Connects to `/chat`** — same backend as the CLI
- **Context-aware** — on the stats page, pre-loaded with market analysis prompts; on the search page, card clicks pre-fill the chat input
- **Badge** — attention dot appears after 4 s idle

---

## Architecture

```
app.py / server.py
  └─ PropertyAssistant (agent.py)
       ├─ OpenAI LLM — picks tool + parameters from conversation history
       ├─ _execute_tool() — dispatches to tools.py, updates SessionMemory
       └─ _handle_simple_followup() — fast-path for neighborhood-swap queries

tools.py — four callable tools with OpenAI-compatible JSON schemas
  ├─ search_properties()   — filter property + transaction rows
  ├─ get_market_stats()    — aggregate analytics (median/avg price, RON/mp)
  ├─ lookup_owner()        — ownership lookup by address / propkey / owner
  └─ describe_schema()     — field list, date range, geocoding status, caveats

data_loader.py — loads & validates three CSVs into PropertyDataStore (in-memory)
  └─ calls geocoder.enrich_with_geocoding() at load time

geocoder.py — Nominatim (OSM) geocoding
  ├─ Reads cache from data/geocache.json on startup (instant, no API call)
  ├─ Geocodes uncached addresses in a background daemon thread (1 req/s rate limit)
  └─ Adds lat, lng, geo_neighborhood fields to each property in-place

memory.py — SessionMemory tracks last_tool, filters, last_results across turns

server.py — FastAPI
  ├─ GET  /                    → index.html (property search)
  ├─ GET  /stats               → stats.html (market dashboard)
  ├─ GET  /ownership           → ownership.html (ownership search)
  ├─ POST /chat                → PropertyAssistant.ask()
  ├─ POST /reset               → new PropertyAssistant session
  ├─ GET  /api/chart-data      → live aggregations for Chart.js
  └─ GET  /api/ownership-search → paginated ownership search (q, type, limit, offset)
```

### Key design decisions

- **Hallucination prevention** — system prompt forbids invention; all factual answers must come from a tool result; `temperature=0`
- **Forced tool use** — messages containing factual keywords (price, owner, address, etc.) use `tool_choice="required"` so the LLM cannot answer without calling a tool first
- **Address normalization** — `lookup_owner()` expands abbreviations before substring matching (`Bd.` → `Bulevardul`, `Str.` → `Strada`, `Cal.` → `Calea`, etc.) so queries like "Bd. Eroilor" correctly match database addresses
- **Tool outputs carry caveats** — every tool returns `status` (`ok`, `empty`, `error`, `needs_clarification`), result data, and a `caveats` list
- **Neighborhood matching** — the `neighborhood` filter matches directly against the `borough` field (after alias resolution). Real geocoded `geo_neighborhood` from Nominatim takes priority when available. ZIP-based lookup was removed because the dataset's ZIPs are randomly assigned and not neighborhood-specific
- **Geocoding is non-blocking** — first startup triggers background geocoding; the app serves requests immediately using `borough` field matching while geocoding runs in the background

### Constants worth knowing

- `MAX_ROWS_RETURNED = 12` (tools.py) — caps rows returned to the LLM
- `BOROUGH_ALIASES` (tools.py) — maps input variants (unaccented, lowercase) to canonical neighborhood names
- `data/geocache.json` — persisted geocoding results; delete to re-geocode all properties

---

## API Endpoints

### `GET /api/chart-data`

Returns all chart data for the market statistics dashboard. Aggregates live from CSVs.

Response fields: `years`, `price_trend` (overall median + per-borough), `volume_by_year`, `borough_stats`, `ownership_split`, `kpis`.

### `GET /api/ownership-search`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | string | `""` | Full-text search (address, owner name, propkey) |
| `type` | string | `"all"` | Filter: `all`, `srl`, or `individual` |
| `limit` | int | `24` | Max results (1–200) |
| `offset` | int | `0` | Pagination offset |

Response: `{ total, results, stats: { srl, individual } }`

---

## Tools

### `search_properties`

Filters property, ownership, and transaction records.

Supported filters: `borough`, `neighborhood`, `zip`, `is_srl`, `min_sale_price`, `max_sale_price`, `sold_after`, `sold_before`, `years_back`, `property_class_contains`, `limit`

### `get_market_stats`

Calculates market-level statistics.

Supported metrics: `median_price_per_sqft`, `avg_price_per_sqft`, `median_sale_price`, `avg_sale_price`, `count_sales`

Group by: `borough`, `zip`, `property_class`

### `lookup_owner`

Ownership lookup by `address`, `propkey`, or `owner_name_contains`.

### `describe_schema`

Returns field list, date range, available neighborhoods, geocoded count, and data caveats.

---

## Data

- **500 properties** with address, borough, ZIP, property class, building area (mp), assessed value
- **Transactions** covering 2018–2025; sale prices in RON (1 EUR ≈ 5 RON)
- **Ownership** records with SRL flag (derived from owner name patterns)
- Area is measured in **square meters (mp)**
- Sale prices of `0 RON` indicate non-arm's-length transfers
- `is_srl` is derived from owner name patterns, not a source field

### Neighborhoods (15)

Baciu · Borhanci · Bună Ziua · Dâmbul Rotund · Europa · Florești · Gheorgheni · Grigorescu · Iris · Mănăștur · Mărăști · Someșeni · Sopor · Zorilor · Între Lacuri

---

## Dependencies

```
openai>=1.40.0
python-dotenv>=1.0.0
rich>=13.7.0
fastapi>=0.111.0
uvicorn>=0.30.0
geopy>=2.4.0       # OSM Nominatim geocoding (optional — app works without it)
```

---

## About

**Urbantrace** was designed and built by **Sándor Attila Nagy**.

© 2025 Sándor Attila Nagy. All rights reserved.
