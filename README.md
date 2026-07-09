# Urbantrace

## Overview

Urbantrace is an AI-powered research assistant for Cluj-Napoca real estate data. Users query structured property, transaction, and ownership records through natural language and get grounded, data-driven answers.

The core design principle:

> **The LLM plans and explains; deterministic Python tools execute.**

All filtering, aggregation, and joins happen in Python. The LLM never invents property records or calculates values directly. This makes the system auditable and hallucination-resistant.

---

## Key Features

- Natural-language property and ownership search
- Market statistics and trend analysis, filterable by neighborhood, property class, and year range
- Interactive Leaflet map view of listings
- Tool/function-calling agent architecture
- Real neighborhood matching via OSM Nominatim geocoding (with local cache)
- Accounts — register/login, persistent per-user chat history (`/my-chats`), admin panel (`/admin`) for reviewing all sessions
- Contact form (emails the site owner via Resend)
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
├── auth_db.py              # SQLite: users, chat sessions, chat messages, roles
│
├── static/
│   ├── index.html          # Property search page — grid + map view, Brick widget
│   ├── stats.html          # Market statistics page — filterable Chart.js charts
│   ├── ownership.html      # Ownership search page — SRL/individual, infinite scroll
│   ├── login.html          # Register / sign in
│   ├── my-chats.html       # Signed-in user's persisted chat history
│   ├── admin.html          # Admin panel — browse all users' chat sessions
│   └── img/hero-cluj.jpg   # Shared hero photo across index/stats/ownership
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
├── render.yaml             # Render.com deployment config
├── .env.example            # Required environment variables
├── CLAUDE.md               # Claude Code / AI development notes
└── README.md
```

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in the values below
```

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | yes | Powers the Brick agent |
| `OPENAI_MODEL` | no (default `gpt-4o-mini`) | Override the LLM model |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | yes | Seeded once at startup if the account doesn't already exist |
| `SESSION_SECRET` | yes | Signs session cookies — any long random string |
| `RESEND_API_KEY` / `CONTACT_EMAIL_TO` | no | Powers the contact form (resend.com free tier); form returns 503 if unset |
| `ENV` | no (default `development`) | Set to `production` on deploy — enables secure (HTTPS-only) session cookies |

**Run — web interface:**

```bash
python server.py
```

| URL | Page |
|---|---|
| `http://127.0.0.1:8000` | Property search (grid + map view) |
| `http://127.0.0.1:8000/stats` | Market statistics dashboard |
| `http://127.0.0.1:8000/ownership` | Ownership search |
| `http://127.0.0.1:8000/login` | Register / sign in |
| `http://127.0.0.1:8000/my-chats` | Signed-in user's chat history |
| `http://127.0.0.1:8000/admin` | Admin panel (requires `role=admin`) |

**Run — CLI:**

```bash
python app.py
```

---

## Web Interface

All pages share a common design: glassmorphism sticky header with `backdrop-filter: blur`, Inter font, a full nav (Search · Map · Market Stats · Ownership · About · Contact) with a working hamburger menu on mobile, and the Brick assistant widget fixed in the bottom-right corner.

### Property Search (`/`)

- Hero search bar — keyword search across address, neighborhood, owner
- **Real-data example chips** — 4 address chips picked from diverse neighborhoods, sourced live from the database, pre-fill the search bar on click
- Filter chips — neighborhood dropdown (12 neighborhoods), ownership type (SRL / Individual / All), price range bands calibrated to actual RON distribution:
  - `< 500k RON` · `500k – 2M` · `2M – 10M` · `10M – 30M` · `> 30M RON`
- Property cards — SVG building illustrations, price, area (mp), price/mp, owner badge; 24 cards per page with **Load more** pagination
- **8 sort options**: Price high→low, Price low→high, Price/m² high→low, Price/m² low→high, Area large→small, Area small→large, Most recent sale, Oldest sale — sorting applies to the full filtered dataset and shows all results at once
- **Map view** — toggle between grid and an embedded Leaflet map with a pin per listing (`view-btn-map` / `view-btn-grid`); the nav's "Map" link jumps here from any page via `/?view=map`
- Filter bar **stays visible while scrolling** on mobile (sticky, z-index below the hamburger nav)
- Clicking a card pre-fills the Brick assistant with a question about that property

### Market Statistics (`/stats`)

Powered by the `/api/chart-data` endpoint, which aggregates live from the CSV data and accepts `borough`, `property_class`, `year_from`, `year_to` query params.

- **Filter bar** — Neighborhood, Property Class, and Year range (From/To, populated from the actual transaction years) selects, plus a Reset button. Changing any filter refetches and rebuilds every KPI/chart below.

**KPI cards:**

| Card | Value |
|---|---|
| Total Transactions | Count of arm's-length sales (within the active filter) |
| Median Sale Price | Median across matching transactions |
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
- **Infinite scroll** — an `IntersectionObserver` on a bottom sentinel auto-loads the next page (24 records at a time) as the user scrolls, no button click needed

### Accounts (`/login`, `/my-chats`, `/admin`)

- **`/login`** — register or sign in (session-cookie auth, bcrypt-hashed passwords via `auth_db.py`); a guest can also continue without an account
- **`/my-chats`** — a signed-in user's own past Brick conversations, persisted server-side in SQLite and listed by most-recently-active
- **`/admin`** — visible only to the seeded admin account (`role=admin`); lists every user's chat sessions (including guest sessions) and can prune empty guest sessions

### Contact Form

Every page's header has a "Contact" link that opens a dropdown form (name, email, message + a hidden honeypot field against bots). Submissions are emailed to `CONTACT_EMAIL_TO` via the Resend API; the endpoint 503s if `RESEND_API_KEY`/`CONTACT_EMAIL_TO` aren't configured.

### Language Switcher

All pages include a `🇬🇧 EN / 🇷🇴 RO / 🇭🇺 HU` pill switcher in the header (and login screen). The selected language is persisted to `localStorage('ut_lang')` and applied on page load via `data-i18n` / `data-i18n-opt` attributes and a per-page translation table.

### Brick — AI Assistant Widget

A building-brick mascot fixed in the bottom-right corner of every page.

- **Hop animation** — squash-and-stretch jump triggered on card click, after 4 s idle, every 10 s
- **Chat panel** — slides up with a spring animation on click
- **Connects to `/chat`** — same backend as the CLI
- **Context-aware** — on the stats page, pre-loaded with market analysis prompts; on the search page, card clicks pre-fill the chat input
- **Badge** — attention dot appears after 4 s idle

---

## Detailed Workflow

### 1. Guest visitor — search & ask

1. Lands on `/`; `index.html` calls `GET /api/properties-sample` and renders the property grid (24 cards) client-side.
2. Adjusts Neighborhood / Ownership / Price filters or the sort dropdown — all filtering/sorting happens **client-side** against the already-fetched sample, so it's instant.
3. Toggles **Map** — same dataset, rendered as Leaflet pins using each property's `lat`/`lng` (real geocoding takes priority; ungeocoded properties fall back to a deterministic jittered point near their borough's centroid so pins don't stack).
4. Clicks a property card → the Brick panel opens with a pre-filled question about that property, or opens it manually and types a question.
5. Each message is `POST /chat`ed. `server.py` resolves a `chat_session_id` (creating a guest one via `SessionMiddleware` if none exists), fetches or creates a per-session `PropertyAssistant` (`agent.py`), and calls `assistant.ask(text)`.
6. The agent sends the conversation to the OpenAI LLM with the four tool schemas from `tools.py`. The LLM never answers factual questions directly — it must call a tool (`search_properties`, `get_market_stats`, `lookup_owner`, or `describe_schema`); `_execute_tool()` runs it against the in-memory `PropertyDataStore` and updates `SessionMemory` so a follow-up like "what about Grigorescu?" can reuse the prior filters.
7. Both the user's message and the assistant's reply are persisted to SQLite via `auth_db.add_message()` — guest sessions included, keyed only by the anonymous `chat_session_id`.

### 2. Returning / signed-in user

1. Visits `/login`, registers or signs in (`POST /auth/register` / `POST /auth/login`) — passwords are bcrypt-hashed, failed attempts are rate-limited per IP+username.
2. On success the session cookie carries `user_id`, `username`, `role`, and a **fresh** chat session is started (a signed-in user never silently inherits an in-progress guest conversation).
3. Chatting with Brick from any page now persists under that `user_id`. Visiting `/my-chats` calls `GET /api/my-chats` (list) and `GET /api/my-chats/{session_id}` (transcript) — both scoped to the caller, so one user can never read another's history.

### 3. Admin oversight

1. The account named in `ADMIN_USERNAME`/`ADMIN_PASSWORD` is seeded once at first server startup (`auth_db._seed_admin()`) with `role='admin'`.
2. Signing in as that account and visiting `/admin` calls `GET /api/admin/sessions`, which — unlike `/api/my-chats` — returns **every** session, including anonymous guest ones, for support/debugging.
3. `POST /api/admin/prune-guests` deletes guest sessions older than 7 days that never got a message, to keep the DB from accumulating abandoned sessions.

### 4. Market Stats filtering

1. `/stats` loads unfiltered (`GET /api/chart-data`) and populates the Year From/To selects from the response's actual `years` range.
2. Picking a Neighborhood, Property Class, or Year bound calls `applyFilters()`, which rebuilds the query string and re-requests `/api/chart-data?borough=...&property_class=...&year_from=...&year_to=...`.
3. The server re-filters `store.transactions` (and the joined `store.property_ownership` for the SRL/individual split) against the same predicate, so every KPI and chart — not just one — reflects the active filter. The frontend destroys and recreates each Chart.js instance rather than mutating in place, so filter changes never leave stale datasets overlapping the canvas.

### 5. Deployment (Render)

1. `render.yaml` defines a single free-tier web service running `uvicorn server:app`.
2. Secrets (`OPENAI_API_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `RESEND_API_KEY`, `CONTACT_EMAIL_TO`) are marked `sync: false` and must be set in the Render dashboard; `SESSION_SECRET` is auto-generated; `ENV=production` flips session cookies to HTTPS-only.
3. On first boot in a fresh environment, `lifespan()` loads the CSVs into memory, `auth_db.init_db()` creates the SQLite schema, and the admin account is seeded — no manual migration step.

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

auth_db.py — SQLite (users, chat_sessions, chat_messages)
  ├─ create_user() / authenticate_user() — bcrypt-hashed passwords
  ├─ _seed_admin() — creates ADMIN_USERNAME/ADMIN_PASSWORD on first startup if missing
  ├─ create_chat_session() / add_message() / get_messages() — persisted chat history
  └─ get_sessions_for_user() / get_all_sessions() — used by /my-chats and /admin

server.py — FastAPI
  ├─ GET  /                       → index.html (property search + map view)
  ├─ GET  /stats                  → stats.html (market dashboard)
  ├─ GET  /ownership              → ownership.html (ownership search)
  ├─ GET  /login                  → login.html
  ├─ GET  /my-chats               → my-chats.html
  ├─ GET  /admin                  → admin.html
  ├─ GET  /api/me                 → current session identity/role
  ├─ POST /auth/register          → create account, start session
  ├─ POST /auth/login             → authenticate, start session (rate-limited)
  ├─ POST /auth/logout            → clear session
  ├─ POST /chat                   → PropertyAssistant.ask(), persists to auth_db
  ├─ POST /reset                  → new chat session ("New Chat")
  ├─ GET  /api/my-chats           → signed-in user's session list
  ├─ GET  /api/my-chats/{id}      → one session's messages (owner-only)
  ├─ GET  /api/admin/sessions     → all sessions (admin-only)
  ├─ GET  /api/admin/sessions/{id}→ one session's messages (admin-only)
  ├─ POST /api/admin/prune-guests → delete empty guest sessions (admin-only)
  ├─ POST /api/contact            → sends an email via Resend (rate-limited, honeypot)
  ├─ GET  /api/properties-sample  → property listings incl. map lat/lng
  ├─ GET  /api/chart-data         → live aggregations for Chart.js (borough, property_class, year_from, year_to)
  └─ GET  /api/ownership-search   → paginated ownership search (q, type, limit, offset)
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

Returns all chart data for the market statistics dashboard. Aggregates live from CSVs, re-filtered on every call.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `borough` | string | `"All"` | Neighborhood filter |
| `property_class` | string | `"All"` | Property class filter (exact match, e.g. `"D - Bloc Cu Lift"`) |
| `year_from` | int | none | Earliest sale year (inclusive) |
| `year_to` | int | none | Latest sale year (inclusive) |

Response fields: `years`, `price_trend` (overall median + per-borough), `volume_by_year`, `borough_stats`, `ownership_split`, `kpis`.

### `GET /api/ownership-search`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | string | `""` | Full-text search (address, owner name, propkey) |
| `type` | string | `"all"` | Filter: `all`, `srl`, or `individual` |
| `limit` | int | `24` | Max results (1–200) |
| `offset` | int | `0` | Pagination offset |

Response: `{ total, results, stats: { srl, individual } }`. The ownership page calls this repeatedly with increasing `offset` as the user scrolls (infinite scroll), not via a "Load more" click.

### `GET /api/properties-sample`

Returns every property's best (highest-price) transaction plus `lat`/`lng` (real geocoded coordinates when available, otherwise a deterministic per-borough fallback jitter). Powers both the property grid and the map view on `/`.

### Auth & chat history

`POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /api/me` manage a session-cookie identity. `POST /chat` and `POST /reset` work for both guests and signed-in users; signed-in users additionally get `GET /api/my-chats` and `GET /api/my-chats/{session_id}` to retrieve their own persisted history. `GET/POST /api/admin/*` are gated on `role=admin` (seeded via `ADMIN_USERNAME`/`ADMIN_PASSWORD`) and expose every user's — including guests' — chat sessions.

### `POST /api/contact`

Rate-limited (per-IP), honeypot-protected contact form submission, relayed by email via the Resend API. Returns `503` if `RESEND_API_KEY`/`CONTACT_EMAIL_TO` are not set.

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

### Neighborhoods (12)

Bună Ziua · Centru · Dâmbul Rotund · Europa · Florești · Gheorgheni · Grigorescu · Iris · Mănăștur · Mărăști · Someșeni · Zorilor

---

## Dependencies

```
openai>=1.40.0
python-dotenv>=1.0.0
rich>=13.7.0
fastapi>=0.111.0
uvicorn>=0.30.0
geopy>=2.4.0       # OSM Nominatim geocoding (optional — app works without it)
bcrypt>=4.1.0      # password hashing (auth_db.py)
itsdangerous>=2.2.0 # signed session cookies (SessionMiddleware)
```

---

## About

**Urbantrace** was designed and built by **Sándor Attila Nagy**.

© 2025 Sándor Attila Nagy. All rights reserved.
