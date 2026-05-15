from __future__ import annotations

import os
import threading
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from statistics import median as _median

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from data_loader import load_data, PropertyDataStore
from agent import PropertyAssistant

load_dotenv()

_data_store: PropertyDataStore | None = None
_assistant: PropertyAssistant | None = None
_lock = threading.Lock()

_static = Path(__file__).parent / "static"
_HTML           = (_static / "index.html").read_text(encoding="utf-8")
_STATS_HTML     = (_static / "stats.html").read_text(encoding="utf-8") if (_static / "stats.html").exists() else "<h1>Stats page not ready</h1>"
_OWNERSHIP_HTML = (_static / "ownership.html").read_text(encoding="utf-8") if (_static / "ownership.html").exists() else "<h1>Ownership page not ready</h1>"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _data_store, _assistant
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to your .env file.")
    data_dir = Path(__file__).parent / "data"
    _data_store = load_data(data_dir)
    _assistant = PropertyAssistant(_data_store)
    yield


app = FastAPI(title="UrbanTrace AI", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str


@app.get("/", response_class=HTMLResponse)
def root():
    return _HTML


@app.get("/stats", response_class=HTMLResponse)
def stats_page():
    return (_static / "stats.html").read_text(encoding="utf-8")


@app.get("/ownership", response_class=HTMLResponse)
def ownership_page():
    return (_static / "ownership.html").read_text(encoding="utf-8")


@app.post("/chat")
def chat(body: ChatRequest):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    with _lock:
        try:
            response = _assistant.ask(body.message.strip())
            return {"response": response}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


@app.post("/reset")
def reset():
    global _assistant
    with _lock:
        _assistant = PropertyAssistant(_data_store)
    return {"status": "ok"}


@app.get("/api/chart-data")
def chart_data():
    if not _data_store:
        raise HTTPException(status_code=503, detail="Data not loaded.")
    return _compute_chart_data(_data_store)


@app.get("/api/ownership-search")
def ownership_search(
    q: str = Query(default="", description="Search query"),
    type: str = Query(default="all", description="Filter type: all | srl | individual"),
    limit: int = Query(default=24, ge=1, le=200, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
):
    if not _data_store:
        raise HTTPException(status_code=503, detail="Data not loaded.")

    records = list(_data_store.property_ownership)

    # Type filter
    if type == "srl":
        records = [r for r in records if r.get("is_srl")]
    elif type == "individual":
        records = [r for r in records if not r.get("is_srl")]

    # Text search
    if q:
        q_lower = q.lower()
        records = [
            r for r in records
            if q_lower in str(r.get("address", "")).lower()
            or q_lower in str(r.get("owner_name", "")).lower()
            or q_lower in str(r.get("propkey", "")).lower()
        ]

    # Compute stats on the full filtered set (before pagination)
    srl_count = sum(1 for r in records if r.get("is_srl"))
    ind_count = len(records) - srl_count
    total = len(records)

    # Pagination
    paginated = records[offset: offset + limit]

    # Serialize results
    results = []
    for r in paginated:
        reg_date = r.get("registration_date")
        results.append({
            "propkey":           r.get("propkey"),
            "address":           r.get("address", ""),
            "borough":           r.get("borough", ""),
            "owner_name":        r.get("owner_name", ""),
            "owner_type":        r.get("owner_type", ""),
            "is_srl":            bool(r.get("is_srl", False)),
            "registration_date": str(reg_date) if reg_date is not None else None,
            "assessed_value":    r.get("assessed_value") or 0,
        })

    return {
        "total":   total,
        "results": results,
        "stats":   {"srl": srl_count, "individual": ind_count},
    }


def _compute_chart_data(store: PropertyDataStore) -> dict:
    valid_txs = [
        tx for tx in store.transactions
        if tx.get("sale_price", 0) > 1000 and tx.get("sale_date")
    ]

    all_years = sorted({tx["sale_date"].year for tx in valid_txs})

    vol_by_year: dict[int, int] = defaultdict(int)
    prices_by_year: dict[int, list[float]] = defaultdict(list)
    psqm_by_year: dict[int, list[float]] = defaultdict(list)
    borough_prices: dict[str, list[float]] = defaultdict(list)
    borough_psqm: dict[str, list[float]] = defaultdict(list)
    borough_prices_by_year: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))

    for tx in valid_txs:
        yr = tx["sale_date"].year
        price = float(tx["sale_price"])
        vol_by_year[yr] += 1
        prices_by_year[yr].append(price)

        prop = store.properties_by_propkey.get(tx["propkey"])
        if prop:
            borough = str(prop.get("borough", "")).strip()
            if borough:
                borough_prices[borough].append(price)
                borough_prices_by_year[borough][yr].append(price)
            sf = prop.get("building_sf", 0) or 0
            if sf > 0:
                psq = price / sf
                psqm_by_year[yr].append(psq)
                if borough:
                    borough_psqm[borough].append(psq)

    top_boroughs = sorted(borough_prices, key=lambda b: len(borough_prices[b]), reverse=True)[:8]

    srl_count = sum(1 for o in store.ownership if o.get("is_srl"))
    ind_count = len(store.ownership) - srl_count

    all_prices = [tx["sale_price"] for tx in valid_txs]
    all_psqm: list[float] = []
    for tx in valid_txs:
        prop = store.properties_by_propkey.get(tx["propkey"])
        if prop and (prop.get("building_sf") or 0) > 0:
            all_psqm.append(tx["sale_price"] / prop["building_sf"])

    yoy = None
    if len(all_years) >= 2:
        last_y, prev_y = all_years[-1], all_years[-2]
        lm = _median(prices_by_year[last_y]) if prices_by_year.get(last_y) else None
        pm = _median(prices_by_year[prev_y]) if prices_by_year.get(prev_y) else None
        if lm and pm:
            yoy = round((lm - pm) / pm * 100, 1)

    return {
        "years": [str(y) for y in all_years],
        "price_trend": {
            "overall_median": [
                round(_median(prices_by_year[y])) if prices_by_year.get(y) else None
                for y in all_years
            ],
            "overall_psqm": [
                round(_median(psqm_by_year[y])) if psqm_by_year.get(y) else None
                for y in all_years
            ],
            "by_borough": {
                b: [
                    round(_median(borough_prices_by_year[b][y]))
                    if borough_prices_by_year[b].get(y) else None
                    for y in all_years
                ]
                for b in top_boroughs[:5]
            },
        },
        "volume_by_year": [vol_by_year.get(y, 0) for y in all_years],
        "borough_stats": {
            "labels":       top_boroughs,
            "median_price": [round(_median(borough_prices[b])) for b in top_boroughs],
            "median_psqm":  [round(_median(borough_psqm[b])) if borough_psqm.get(b) else 0 for b in top_boroughs],
            "count":        [len(borough_prices[b]) for b in top_boroughs],
        },
        "ownership_split": {"srl": srl_count, "individual": ind_count},
        "kpis": {
            "median_price":       round(_median(all_prices)) if all_prices else 0,
            "total_transactions": len(valid_txs),
            "median_psqm":        round(_median(all_psqm)) if all_psqm else 0,
            "yoy_change":         yoy,
            "total_properties":   len(store.properties),
            "srl_pct":            round(srl_count / len(store.ownership) * 100, 1) if store.ownership else 0,
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
