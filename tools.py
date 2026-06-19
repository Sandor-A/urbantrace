from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from statistics import median, mean
from typing import Any

from data_loader import PropertyDataStore, parse_date

MAX_ROWS_RETURNED = 12

# ZIP→neighborhood was removed: the ZIP codes in this dataset are not reliably
# mapped to neighborhoods. Use the `borough` field (or geocoded `geo_neighborhood`).

BOROUGH_ALIASES = {
    "centru": "Centru",
    "center": "Centru",
    "centrum": "Centru",
    "marasti": "Mărăști",
    "mărăști": "Mărăști",
    "gheorgheni": "Gheorgheni",
    "manastur": "Mănăștur",
    "mănăștur": "Mănăștur",
    "floresti": "Florești",
    "florești": "Florești",
    "grigorescu": "Grigorescu",
    "zorilor": "Zorilor",
    "buna ziua": "Bună Ziua",
    "bună ziua": "Bună Ziua",
    "sopor": "Sopor",
    "europa": "Europa",
    "borhanci": "Borhanci",
    "dambul rotund": "Dâmbul Rotund",
    "dâmbul rotund": "Dâmbul Rotund",
    "intre lacuri": "Între Lacuri",
    "între lacuri": "Între Lacuri",
    "iris": "Iris",
    "someseni": "Someșeni",
    "someșeni": "Someșeni",
    "baciu": "Baciu",
}


@dataclass
class ToolResult:
    status: str
    message: str
    data: Any
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ADDR_EXPANSIONS = {
    "bd.": "bulevardul", "bul.": "bulevardul",
    "str.": "strada", "st.": "strada",
    "cal.": "calea", "cl.": "calea",
    "aleea": "aleea", "al.": "aleea",
    "pta.": "piața", "p-ta.": "piața",
}


def _normalize_addr(addr: str) -> str:
    parts = addr.lower().split()
    return " ".join(_ADDR_EXPANSIONS.get(p, p) for p in parts)


def _clean_borough(value: str | None) -> str | None:
    if not value:
        return None
    return BOROUGH_ALIASES.get(str(value).strip().lower(), str(value).strip().title())


def _date_to_str(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, date) else None


def _format_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for k, v in list(out.items()):
        if isinstance(v, date):
            out[k] = v.isoformat()
    return out


def _passes_property_filters(
    row: dict[str, Any],
    borough: str | None = None,
    zip: str | None = None,
    neighborhood: str | None = None,
    is_srl: bool | None = None,
    property_class_contains: str | None = None,
) -> tuple[bool, list[str]]:
    notes: list[str] = []

    if neighborhood and not zip:
        norm = _clean_borough(neighborhood) or neighborhood.strip()

        # 1. Real geocoded neighborhood from Nominatim (most accurate)
        geo = str(row.get("geo_neighborhood") or "").strip()
        # 2. Borough field from the CSV (ground truth for this dataset)
        row_borough = str(row.get("borough") or "").strip()

        if geo and geo.lower() == norm.lower():
            pass  # matched via real geocoding
        elif row_borough.lower() == norm.lower():
            pass  # matched via borough field
        else:
            return False, notes

    if borough:
        cleaned = _clean_borough(borough)
        if str(row.get("borough", "")).lower() != str(cleaned).lower():
            return False, notes

    if zip:
        z = str(zip).strip().replace(".0", "").zfill(5)
        if str(row.get("zip", "")).zfill(5) != z:
            return False, notes

    if is_srl is not None and bool(row.get("is_srl")) != bool(is_srl):
        return False, notes

    if property_class_contains:
        if property_class_contains.lower() not in str(row.get("property_class", "")).lower():
            return False, notes

    return True, notes


def _joined_rows(store: PropertyDataStore):
    for prop in store.properties:
        owner = store.ownership_by_propkey.get(prop["propkey"], {})
        txs = store.transactions_by_propkey.get(prop["propkey"], [])
        if not txs:
            yield {**prop, **owner, "sale_date": None, "sale_price": None, "transaction_type": None, "buyer_name": None, "seller_name": None}
        else:
            for tx in txs:
                yield {**prop, **owner, **tx}


def search_properties(
    store: PropertyDataStore,
    borough: str | None = None,
    zip: str | None = None,
    neighborhood: str | None = None,
    is_srl: bool | None = None,
    min_sale_price: float | None = None,
    max_sale_price: float | None = None,
    sold_after: str | None = None,
    sold_before: str | None = None,
    years_back: int | None = None,
    property_class_contains: str | None = None,
    limit: int = MAX_ROWS_RETURNED,
) -> dict[str, Any]:
    notes: list[str] = []
    after = parse_date(sold_after) if sold_after else None
    before = parse_date(sold_before) if sold_before else None

    if years_back is not None:
        # Approximation avoids external date dependencies. Good enough for filter demo.
        after = date.today() - timedelta(days=365 * int(years_back))
        notes.append(f"years_back={years_back} interpreted relative to today's date: {after.isoformat()}.")

    matches: list[dict[str, Any]] = []
    local_notes_seen: set[str] = set()

    for row in _joined_rows(store):
        keep, local_notes = _passes_property_filters(row, borough, zip, neighborhood, is_srl, property_class_contains)
        for note in local_notes:
            if note not in local_notes_seen:
                notes.append(note)
                local_notes_seen.add(note)
        if not keep:
            continue

        sale_price = row.get("sale_price")
        sale_date = row.get("sale_date")
        if min_sale_price is not None and (sale_price is None or sale_price < float(min_sale_price)):
            continue
        if max_sale_price is not None and (sale_price is None or sale_price > float(max_sale_price)):
            continue
        if after and (not sale_date or sale_date < after):
            continue
        if before and (not sale_date or sale_date > before):
            continue

        matches.append(row)

    matches.sort(key=lambda r: (_date_to_str(r.get("sale_date")) or "", r.get("sale_price") or 0), reverse=True)
    sample = []
    for row in matches[: min(limit, MAX_ROWS_RETURNED)]:
        sample.append(_format_row({
            "propkey": row.get("propkey"),
            "address": row.get("address"),
            "borough": row.get("borough"),
            "zip": row.get("zip"),
            "property_class": row.get("property_class"),
            "building_sf": row.get("building_sf"),
            "units": row.get("units"),
            "owner_name": row.get("owner_name"),
            "owner_type": row.get("owner_type"),
            "is_srl": row.get("is_srl"),
            "sale_date": row.get("sale_date"),
            "sale_price": row.get("sale_price"),
            "transaction_type": row.get("transaction_type"),
        }))

    return ToolResult(
        status="ok" if matches else "empty",
        message=f"Found {len(matches):,} matching property/transaction rows. Returning top {len(sample):,}." if matches else "No matching records found for the requested filters.",
        data=sample,
        metadata={"total_matches": len(matches), "notes": notes, "max_rows_returned": MAX_ROWS_RETURNED},
    ).to_dict()


def get_market_stats(
    store: PropertyDataStore,
    boroughs: list[str] | None = None,
    borough: str | None = None,
    zip: str | None = None,
    neighborhood: str | None = None,
    metric: str = "median_price_per_sqft",
    group_by: str | None = None,
    min_sale_price: float | None = 1,
    sold_after: str | None = None,
    sold_before: str | None = None,
) -> dict[str, Any]:
    supported_metrics = {"median_price_per_sqft", "avg_price_per_sqft", "median_sale_price", "avg_sale_price", "count_sales"}
    if metric not in supported_metrics:
        return ToolResult("error", f"Unsupported metric '{metric}'.", [], {"supported_metrics": sorted(supported_metrics)}).to_dict()
    if group_by and group_by not in {"borough", "zip", "property_class"}:
        return ToolResult("error", f"Unsupported group_by '{group_by}'.", [], {"supported_group_by": ["borough", "zip", "property_class"]}).to_dict()

    after = parse_date(sold_after) if sold_after else None
    before = parse_date(sold_before) if sold_before else None
    borough_set = {_clean_borough(b) for b in boroughs} if boroughs else None

    values_by_group: dict[str, list[float]] = {}
    sample_count_by_group: dict[str, int] = {}
    notes: list[str] = []
    notes_seen: set[str] = set()

    for row in _joined_rows(store):
        keep, local_notes = _passes_property_filters(row, borough, zip, neighborhood)
        for note in local_notes:
            if note not in notes_seen:
                notes.append(note)
                notes_seen.add(note)
        if not keep:
            continue
        if borough_set and row.get("borough") not in borough_set:
            continue
        sale_price = row.get("sale_price") or 0
        building_sf = row.get("building_sf") or 0
        sale_date = row.get("sale_date")
        if sale_price < float(min_sale_price or 0):
            continue
        if after and (not sale_date or sale_date < after):
            continue
        if before and (not sale_date or sale_date > before):
            continue
        if metric in {"median_price_per_sqft", "avg_price_per_sqft"} and building_sf <= 0:
            continue

        group_key = str(row.get(group_by)) if group_by else "overall"
        sample_count_by_group[group_key] = sample_count_by_group.get(group_key, 0) + 1
        if metric in {"median_price_per_sqft", "avg_price_per_sqft"}:
            value = sale_price / building_sf
        elif metric in {"median_sale_price", "avg_sale_price"}:
            value = float(sale_price)
        else:
            value = 1.0
        values_by_group.setdefault(group_key, []).append(value)

    rows: list[dict[str, Any]] = []
    for group_key, values in values_by_group.items():
        if metric.startswith("median"):
            value = median(values)
        elif metric.startswith("avg"):
            value = mean(values)
        else:
            value = len(values)
        row = {"metric": metric, "value": round(float(value), 2), "sample_size": sample_count_by_group.get(group_key, len(values))}
        if group_by:
            row[group_by] = group_key
        rows.append(row)

    rows.sort(key=lambda r: r.get("value") or 0, reverse=True)
    return ToolResult(
        status="ok" if rows else "empty",
        message=f"Calculated {metric} using {sum(sample_count_by_group.values()):,} sale rows." if rows else "No sales available for the requested filters.",
        data=rows,
        metadata={"notes": notes, "metric": metric, "group_by": group_by},
    ).to_dict()


def lookup_owner(
    store: PropertyDataStore,
    address: str | None = None,
    propkey: int | None = None,
    owner_name_contains: str | None = None,
    limit: int = MAX_ROWS_RETURNED,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for row in store.property_ownership:
        if propkey is not None and row.get("propkey") != int(propkey):
            continue
        if address:
            query_norm = _normalize_addr(address)
            row_norm = _normalize_addr(str(row.get("address", "")))
            if query_norm not in row_norm:
                continue
        if owner_name_contains and owner_name_contains.lower() not in str(row.get("owner_name", "")).lower():
            continue
        if not any([address, propkey is not None, owner_name_contains]):
            return ToolResult("needs_clarification", "Provide an address, propkey, or owner name to look up ownership.", [], {}).to_dict()
        matches.append(row)

    sample = [_format_row({
        "propkey": row.get("propkey"),
        "address": row.get("address"),
        "borough": row.get("borough"),
        "zip": row.get("zip"),
        "owner_name": row.get("owner_name"),
        "owner_type": row.get("owner_type"),
        "is_srl": row.get("is_srl"),
        "registration_date": row.get("registration_date"),
        "assessed_value": row.get("assessed_value"),
    }) for row in matches[: min(limit, MAX_ROWS_RETURNED)]]

    return ToolResult(
        status="ok" if matches else "empty",
        message=f"Found {len(matches):,} matching ownership records. Returning top {len(sample):,}." if matches else "No ownership records matched the request.",
        data=sample,
        metadata={"total_matches": len(matches), "max_rows_returned": MAX_ROWS_RETURNED},
    ).to_dict()


def describe_schema(store: PropertyDataStore) -> dict[str, Any]:
    sale_dates = [tx["sale_date"] for tx in store.transactions if tx.get("sale_date")]
    data = {
        "properties": ["propkey", "address", "borough", "zip", "property_class", "building_sf", "lot_sf", "year_built", "units", "assessed_value"],
        "ownership": ["propkey", "owner_name", "owner_type", "is_srl", "registration_date"],
        "transactions": ["id", "propkey", "sale_date", "sale_price", "buyer_name", "seller_name", "transaction_type"],
        "available_geographies": {
            "boroughs": sorted({p["borough"] for p in store.properties if p.get("borough")}),
            "zip_count": len({p["zip"] for p in store.properties if p.get("zip")}),
            "geocoded_count": sum(1 for p in store.properties if p.get("lat")),
            "note": (
                "Use 'borough' or 'neighborhood' interchangeably — both match the borough field. "
                "Real geocoded coordinates (lat/lng) are available for properties that have been "
                "geocoded via OSM Nominatim. Geocoding runs in the background on first startup."
            ),
        },
        "date_range": {
            "min_sale_date": min(sale_dates).isoformat() if sale_dates else None,
            "max_sale_date": max(sale_dates).isoformat() if sale_dates else None,
        },
    }
    return ToolResult("ok", "Schema and dataset limitations returned.", data, {}).to_dict()


TOOL_FUNCTIONS = {
    "search_properties": search_properties,
    "get_market_stats": get_market_stats,
    "lookup_owner": lookup_owner,
    "describe_schema": describe_schema,
}

OPENAI_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_properties",
            "description": "Search property, ownership, and transaction records using filters like neighborhood, ZIP, SRL ownership, price, and sale date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "borough": {"type": "string", "description": "Cluj-Napoca neighborhood (cartier), e.g. Gheorgheni or Mărăști."},
                    "zip": {"type": "string", "description": "Five-digit ZIP code."},
                    "neighborhood": {"type": "string", "description": "Neighborhood name. Only limited configured mappings exist; otherwise ask for ZIP."},
                    "is_srl": {"type": "boolean", "description": "Whether current owner is an SRL (Societate cu Răspundere Limitată)."},
                    "min_sale_price": {"type": "number"},
                    "max_sale_price": {"type": "number"},
                    "sold_after": {"type": "string", "description": "YYYY-MM-DD date."},
                    "sold_before": {"type": "string", "description": "YYYY-MM-DD date."},
                    "years_back": {"type": "integer", "description": "Filter to sales within the last N years from today."},
                    "property_class_contains": {"type": "string"},
                    "limit": {"type": "integer", "default": 12},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_stats",
            "description": "Calculate market statistics such as median price per square foot, median sale price, average sale price, or sales count.",
            "parameters": {
                "type": "object",
                "properties": {
                    "boroughs": {"type": "array", "items": {"type": "string"}, "description": "Use for comparing multiple boroughs."},
                    "borough": {"type": "string"},
                    "zip": {"type": "string"},
                    "neighborhood": {"type": "string"},
                    "metric": {"type": "string", "enum": ["median_price_per_sqft", "avg_price_per_sqft", "median_sale_price", "avg_sale_price", "count_sales"]},
                    "group_by": {"type": "string", "enum": ["borough", "zip", "property_class"]},
                    "min_sale_price": {"type": "number", "default": 1},
                    "sold_after": {"type": "string"},
                    "sold_before": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_owner",
            "description": "Look up current ownership records by address, property key, or owner name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "propkey": {"type": "integer"},
                    "owner_name_contains": {"type": "string"},
                    "limit": {"type": "integer", "default": 12},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_schema",
            "description": "Describe available datasets, columns, date range, geographies, and limitations. Use when a user asks for unsupported fields like neighborhood if ambiguous.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]
