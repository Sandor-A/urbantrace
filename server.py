from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict, defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from statistics import median as _median

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

import auth_db
from data_loader import load_data, PropertyDataStore
from agent import PropertyAssistant

load_dotenv()

_IS_PRODUCTION = os.getenv("ENV", "development").lower() == "production"

# Approximate centroids for Cluj-Napoca neighborhoods, used as a fallback
# map location when a property hasn't been geocoded yet (real geocoding via
# geocoder.py runs in the background and takes precedence once available).
_BOROUGH_CENTROIDS: dict[str, tuple[float, float]] = {
    "Centru":          (46.7712, 23.5905),
    "Grigorescu":      (46.7810, 23.5620),
    "Mărăști":         (46.7870, 23.6190),
    "Mănăștur":        (46.7660, 23.5560),
    "Zorilor":         (46.7480, 23.5820),
    "Europa":          (46.7580, 23.5480),
    "Gheorgheni":      (46.7550, 23.6200),
    "Bună Ziua":       (46.7450, 23.6150),
    "Iris":            (46.7944, 23.6061),
    "Florești":        (46.7420, 23.4900),
    "Someșeni":        (46.7830, 23.6650),
    "Dâmbul Rotund":   (46.7950, 23.6350),
}
_CLUJ_CENTER = (46.7704, 23.5914)


def _fallback_latlng(propkey: int, borough: str) -> tuple[float, float]:
    """Deterministic jittered point near a borough's centroid, keyed by propkey
    so the same property always lands on the same pin."""
    base_lat, base_lng = _BOROUGH_CENTROIDS.get(borough, _CLUJ_CENTER)
    # Small deterministic offset (~ +/-300m) so pins spread out instead of stacking.
    jitter_lat = ((propkey * 2654435761) % 1000 / 1000 - 0.5) * 0.006
    jitter_lng = ((propkey * 40503) % 1000 / 1000 - 0.5) * 0.006
    return round(base_lat + jitter_lat, 6), round(base_lng + jitter_lng, 6)

_data_store: PropertyDataStore | None = None
_static = Path(__file__).parent / "static"

# ── Per-session assistant cache ──────────────────────────────────────────────
# Replaces the old single-global-assistant model: each chat_session_id gets its
# own PropertyAssistant, capped with LRU eviction so a busy day doesn't grow
# server RAM unbounded. A per-session lock (not one global lock) means one
# visitor's in-flight request no longer serializes every other visitor's chat.
_MAX_CACHED_ASSISTANTS = 200
_assistants: OrderedDict[str, PropertyAssistant] = OrderedDict()
_assistant_locks: dict[str, threading.Lock] = {}
_cache_lock = threading.Lock()

# ── Login rate limiting ───────────────────────────────────────────────────────
_RATE_LIMIT_WINDOW_S = 15 * 60
_RATE_LIMIT_MAX_ATTEMPTS = 5
_login_attempts: dict[str, list[float]] = defaultdict(list)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _data_store
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to your .env file.")
    data_dir = Path(__file__).parent / "data"
    _data_store = load_data(data_dir)
    auth_db.init_db()
    yield


app = FastAPI(title="UrbanTrace AI", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-only-insecure-secret"),
    session_cookie="ut_session",
    max_age=30 * 24 * 60 * 60,
    same_site="lax",
    https_only=_IS_PRODUCTION,
)
app.mount("/img", StaticFiles(directory=_static / "img"), name="img")


def _assistant_lock(session_id: str) -> threading.Lock:
    with _cache_lock:
        return _assistant_locks.setdefault(session_id, threading.Lock())


def _get_assistant(session_id: str) -> PropertyAssistant:
    with _cache_lock:
        cached = _assistants.get(session_id)
        if cached is not None:
            _assistants.move_to_end(session_id)
            return cached

    assistant = PropertyAssistant(_data_store)
    stored = auth_db.get_messages(session_id)
    if stored:
        # Rehydrate simplified {role, content} turns after the system prompt.
        # This restores conversation text across restarts, but not the exact
        # tool-call chain or in-memory SessionMemory follow-up state.
        assistant.messages = assistant.messages[:1] + [
            {"role": m["role"], "content": m["content"]} for m in stored
        ]

    with _cache_lock:
        _assistants[session_id] = assistant
        _assistants.move_to_end(session_id)
        while len(_assistants) > _MAX_CACHED_ASSISTANTS:
            _assistants.popitem(last=False)
    return assistant


def _active_chat_session_id(request: Request) -> str:
    """Lazily creates a chat_sessions DB row on first real use — never on a
    bare page load — so crawler/bot traffic doesn't grow the DB forever."""
    sid = request.session.get("chat_session_id")
    # Validate the stored session still exists in the DB — it may have been
    # wiped (e.g. Render ephemeral storage restart) while the cookie persists.
    if sid:
        try:
            auth_db.get_session_owner(sid)
        except ValueError:
            sid = None
            request.session.pop("chat_session_id", None)
    if not sid:
        user_id = request.session.get("user_id")
        # Same guard for stale user_id in cookie.
        if user_id and not auth_db.get_user(user_id):
            request.session.clear()
            user_id = None
        sid = auth_db.create_chat_session(user_id)
        request.session["chat_session_id"] = sid
    return sid


def _check_rate_limit(key: str) -> bool:
    now = time.time()
    attempts = _login_attempts[key]
    attempts[:] = [t for t in attempts if now - t < _RATE_LIMIT_WINDOW_S]
    if len(attempts) >= _RATE_LIMIT_MAX_ATTEMPTS:
        return False
    attempts.append(now)
    return True


def _require_admin(request: Request) -> None:
    if request.session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")


class ChatRequest(BaseModel):
    message: str


@app.get("/", response_class=HTMLResponse)
def root():
    return (_static / "index.html").read_text(encoding="utf-8")


@app.get("/stats", response_class=HTMLResponse)
def stats_page():
    return (_static / "stats.html").read_text(encoding="utf-8")


@app.get("/ownership", response_class=HTMLResponse)
def ownership_page():
    return (_static / "ownership.html").read_text(encoding="utf-8")


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return (_static / "login.html").read_text(encoding="utf-8")


@app.get("/my-chats", response_class=HTMLResponse)
def my_chats_page():
    return (_static / "my-chats.html").read_text(encoding="utf-8")


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return (_static / "admin.html").read_text(encoding="utf-8")


class AuthRequest(BaseModel):
    username: str
    password: str


@app.get("/api/me")
def whoami(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return {"authenticated": False, "role": "guest"}
    return {
        "authenticated": True,
        "username": request.session.get("username"),
        "role": request.session.get("role", "user"),
    }


@app.post("/auth/register")
def register(body: AuthRequest, request: Request):
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    user = auth_db.create_user(body.username, body.password)
    if not user:
        raise HTTPException(status_code=409, detail="That username is already taken.")
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["role"] = user["role"]
    return {"status": "ok", "username": user["username"], "role": user["role"]}


@app.post("/auth/login")
def login(body: AuthRequest, request: Request):
    rate_key = f"{request.client.host if request.client else 'unknown'}:{body.username.strip().lower()}"
    if not _check_rate_limit(rate_key):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    user = auth_db.authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password.")

    # Start a fresh chat session on login rather than silently carrying
    # forward an in-progress guest session onto the newly-authenticated user.
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["role"] = user["role"]
    return {"status": "ok", "username": user["username"], "role": user["role"]}


@app.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}


@app.post("/chat")
def chat(body: ChatRequest, request: Request):
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    session_id = _active_chat_session_id(request)
    with _assistant_lock(session_id):
        try:
            assistant = _get_assistant(session_id)
            auth_db.add_message(session_id, "user", text)
            auth_db.set_session_label_if_unset(session_id, text)
            response = assistant.ask(text)
            auth_db.add_message(session_id, "assistant", response)
            return {"response": response}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


@app.post("/reset")
def reset(request: Request):
    """Starts a new chat session ("New Chat") rather than resetting a shared
    global assistant — each visitor now has their own conversation history."""
    request.session.pop("chat_session_id", None)
    return {"status": "ok"}


@app.get("/api/my-chats")
def my_chats(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to view your chat history.")
    return {"sessions": auth_db.get_sessions_for_user(user_id)}


@app.get("/api/my-chats/{session_id}")
def my_chat_detail(session_id: str, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to view your chat history.")
    try:
        owner_id = auth_db.get_session_owner(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    if owner_id != user_id:
        raise HTTPException(status_code=403, detail="That chat doesn't belong to you.")
    return {"messages": auth_db.get_messages(session_id)}


@app.get("/api/admin/sessions")
def admin_sessions(request: Request):
    _require_admin(request)
    return {"sessions": auth_db.get_all_sessions()}


@app.get("/api/admin/sessions/{session_id}")
def admin_session_detail(session_id: str, request: Request):
    _require_admin(request)
    try:
        auth_db.get_session_owner(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return {"messages": auth_db.get_messages(session_id)}


@app.post("/api/admin/prune-guests")
def admin_prune_guests(request: Request):
    _require_admin(request)
    deleted = auth_db.prune_empty_guest_sessions()
    return {"deleted": deleted}


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ContactRequest(BaseModel):
    name: str
    email: str
    message: str
    company: str = ""  # honeypot — real users never fill this; bots often do


@app.post("/api/contact")
def contact(body: ContactRequest, request: Request):
    if body.company.strip():
        # Honeypot tripped — pretend success so bots don't learn to avoid it.
        return {"status": "ok"}

    name = body.name.strip()[:100]
    email = body.email.strip()[:200]
    message = body.message.strip()[:5000]
    if not name or not message or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please provide a valid name, email, and message.")

    rate_key = f"contact:{request.client.host if request.client else 'unknown'}"
    if not _check_rate_limit(rate_key):
        raise HTTPException(status_code=429, detail="Too many messages sent. Try again later.")

    api_key = os.getenv("RESEND_API_KEY")
    to_addr = os.getenv("CONTACT_EMAIL_TO")
    if not api_key or not to_addr:
        raise HTTPException(status_code=503, detail="Contact form is not configured.")

    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": "UrbanTrace Contact <onboarding@resend.dev>",
                "to": [to_addr],
                "reply_to": email,
                "subject": f"UrbanTrace contact form: {name}",
                "text": f"From: {name} <{email}>\n\n{message}",
            },
            timeout=10,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to send message: {exc}")

    return {"status": "ok"}


@app.get("/api/properties-sample")
def properties_sample():
    if not _data_store:
        raise HTTPException(status_code=503, detail="Data not loaded.")

    _PC_TYPE = {
        "a": "house", "b": "townhouse", "c": "apartment",
        "d": "apartment", "e": "modern", "f": "modern",
        "g": "modern", "h": "house",
    }

    result: list[dict] = []
    for prop in _data_store.properties:
        txs = _data_store.transactions_by_propkey.get(prop["propkey"], [])
        best = max(
            (tx for tx in txs if (tx.get("sale_price") or 0) > 1000),
            key=lambda t: t.get("sale_price") or 0,
            default=None,
        )
        if not best:
            continue
        sf = float(prop.get("building_sf") or 0)
        owner = _data_store.ownership_by_propkey.get(prop["propkey"], {})
        pc = str(prop.get("property_class") or "").strip().lower()
        pc_key = pc[0] if pc else ""
        sale_date = best.get("sale_date")
        borough = prop.get("borough", "")
        lat, lng = prop.get("lat"), prop.get("lng")
        if lat is None or lng is None:
            lat, lng = _fallback_latlng(prop["propkey"], borough)
        result.append({
            "propkey":  prop["propkey"],
            "addr":     prop.get("address", ""),
            "hood":     borough,
            "price":    int(best["sale_price"]),
            "sqm":      int(sf),
            "owner":    "SRL" if owner.get("is_srl") else "Individual",
            "date":     sale_date.strftime("%Y-%m") if sale_date else "",
            "type":     _PC_TYPE.get(pc_key, "apartment"),
            "pc":       str(prop.get("property_class") or ""),
            "lat":      lat,
            "lng":      lng,
        })

    result.sort(key=lambda x: -x["price"])
    return result


@app.get("/api/chart-data")
def chart_data(
    borough: str = Query(default="All", description="Neighborhood filter"),
    property_class: str = Query(default="All", description="Property class filter"),
    year_from: int | None = Query(default=None, description="Earliest sale year (inclusive)"),
    year_to: int | None = Query(default=None, description="Latest sale year (inclusive)"),
):
    if not _data_store:
        raise HTTPException(status_code=503, detail="Data not loaded.")
    return _compute_chart_data(_data_store, borough, property_class, year_from, year_to)


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


def _compute_chart_data(
    store: PropertyDataStore,
    borough: str = "All",
    property_class: str = "All",
    year_from: int | None = None,
    year_to: int | None = None,
) -> dict:
    def matches_filters(prop: dict) -> bool:
        if borough != "All" and str(prop.get("borough", "")).strip() != borough:
            return False
        if property_class != "All" and str(prop.get("property_class", "")).strip() != property_class:
            return False
        return True

    valid_txs = []
    for tx in store.transactions:
        if tx.get("sale_price", 0) <= 1000 or not tx.get("sale_date"):
            continue
        yr = tx["sale_date"].year
        if year_from is not None and yr < year_from:
            continue
        if year_to is not None and yr > year_to:
            continue
        prop = store.properties_by_propkey.get(tx["propkey"])
        if not prop or not matches_filters(prop):
            continue
        valid_txs.append(tx)

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

    filtered_ownership = [po for po in store.property_ownership if matches_filters(po)]
    srl_count = sum(1 for po in filtered_ownership if po.get("is_srl"))
    ind_count = len(filtered_ownership) - srl_count

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
            "total_properties":   sum(1 for p in store.properties if matches_filters(p)),
            "srl_pct":            round(srl_count / len(filtered_ownership) * 100, 1) if filtered_ownership else 0,
        },
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
