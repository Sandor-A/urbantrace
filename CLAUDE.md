# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UrbanTrace AI Search Assistant — a Python CLI prototype that lets users query Cluj-Napoca property data (CSV-backed) using natural language. An OpenAI LLM acts as an agent, translating queries into structured tool calls and returning grounded, hallucination-resistant answers.

## Setup & Running

```bash
pip install -r requirements.txt
cp .env.example .env          # add OPENAI_API_KEY
python app.py
```

Override the model via environment variable (default: `gpt-4o-mini`):
```
OPENAI_MODEL=gpt-4o-mini
```

No test runner exists yet. Use `testquestions.txt` for manual QA queries.

## Architecture

The system uses a classic **LLM-as-agent** loop with stateless tool execution:

```
app.py (CLI REPL)
  └─ PropertyAssistant (agent.py)
       ├─ OpenAI LLM — picks tool + parameters from conversation history
       ├─ _execute_tool() — dispatches to tools.py, updates session memory
       └─ _handle_simple_followup() — fast-path for neighborhood-swap queries ("What about Gheorgheni?")

tools.py — four callable tools with OpenAI-compatible JSON schemas
  ├─ search_properties()    — filter property+transaction rows
  ├─ get_market_stats()     — aggregate analytics (median/avg price, $/sqft)
  ├─ lookup_owner()         — current ownership lookup by address/propkey/owner
  └─ describe_schema()      — returns field list, date range, caveats

data_loader.py — loads & validates three CSVs into PropertyDataStore (in-memory)
  ├─ properties.csv  — propkey, address, borough, zip, property_class, building_sf, …
  ├─ ownership.csv   — propkey, owner_name, owner_type, is_srl, registration_date
  └─ transactions.csv — id, propkey, sale_date, sale_price, buyer/seller_name

memory.py — SessionMemory: tracks last_tool, filters, last_results across turns
```

### Key design decisions

- **Hallucination prevention**: system prompt forbids invention; all factual answers must come from a tool result; `temperature=0.1`.
- **Tool outputs carry caveats**: every tool returns `status` (`ok`, `empty`, `error`, `needs_clarification`), result data, and a `caveats` list — the LLM is instructed to surface these.
- **Multi-turn context**: full `messages` list is sent each turn; `SessionMemory` lets the fast-path follow-up skip a redundant LLM call.
- **`_joined_rows()` in tools.py** performs a cartesian join of all three tables at query time (no SQL); filtering happens in `_passes_property_filters()`.

### Hardcoded constants to know about

- `MAX_ROWS_RETURNED = 12` (tools.py) — caps rows returned to the LLM.
- `BOROUGH_ALIASES (neighborhood/cartier aliases)` (tools.py) — maps input variants to canonical names.
- `KNOWN_NEIGHBORHOOD_ZIPS` (tools.py) — only three neighborhoods mapped (Centru, Grigorescu, Europa); neighborhood queries outside these will silently return empty.

## Key Files

| File | Purpose |
|---|---|
| `agent.py` | Agent class, system prompt, tool orchestration |
| `tools.py` | All tool implementations + OpenAI schema definitions |
| `data_loader.py` | CSV ingestion, normalization, index building |
| `memory.py` | Session state for follow-up queries |
| `app.py` | CLI entry point |

## Data Notes

- ZIP codes require normalization (padding, stripping `.0`) — handled in `data_loader.py`.
- `is_srl` is derived from owner name patterns, not a source field.
- Sale prices of `$0` indicate non-arm's-length transfers; not filtered out automatically.
- Transactions cover 2018–2025; properties and ownership are point-in-time snapshots.
