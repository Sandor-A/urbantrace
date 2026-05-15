from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass
class PropertyDataStore:
    properties: list[dict[str, Any]]
    ownership: list[dict[str, Any]]
    transactions: list[dict[str, Any]]
    properties_by_propkey: dict[int, dict[str, Any]]
    ownership_by_propkey: dict[int, dict[str, Any]]
    transactions_by_propkey: dict[int, list[dict[str, Any]]]
    property_ownership: list[dict[str, Any]]


REQUIRED_COLUMNS = {
    "properties": {"propkey", "address", "borough", "zip", "property_class", "building_sf", "lot_sf", "year_built", "units", "assessed_value"},
    "ownership": {"propkey", "owner_name", "owner_type", "is_srl", "registration_date"},
    "transactions": {"id", "propkey", "sale_date", "sale_price", "buyer_name", "seller_name", "transaction_type"},
}


def parse_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value).replace(",", "")))
    except (ValueError, TypeError):
        return default


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def parse_date(value: Any) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_zip(value: Any) -> str:
    raw = str(value).strip().replace(".0", "")
    return raw.zfill(5) if raw else ""


def _read_csv(path: Path, name: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS[name] - fieldnames
        if missing:
            raise ValueError(f"{path.name} is missing required columns: {sorted(missing)}")
        return [dict(row) for row in reader]


def load_data(data_dir: str | Path = "data") -> PropertyDataStore:
    data_dir = Path(data_dir)

    properties = _read_csv(data_dir / "properties.csv", "properties")
    ownership = _read_csv(data_dir / "ownership.csv", "ownership")
    transactions = _read_csv(data_dir / "transactions.csv", "transactions")

    for row in properties:
        row["propkey"] = parse_int(row.get("propkey"))
        row["zip"] = normalize_zip(row.get("zip"))
        row["borough"] = str(row.get("borough", "")).strip()
        row["building_sf"] = parse_int(row.get("building_sf"))
        row["lot_sf"] = parse_int(row.get("lot_sf"))
        row["year_built"] = parse_int(row.get("year_built"))
        row["units"] = parse_int(row.get("units"))
        row["assessed_value"] = parse_int(row.get("assessed_value"))

    for row in ownership:
        row["propkey"] = parse_int(row.get("propkey"))
        row["is_srl"] = parse_bool(row.get("is_srl"))
        row["registration_date"] = parse_date(row.get("registration_date"))

    for row in transactions:
        row["id"] = parse_int(row.get("id"))
        row["propkey"] = parse_int(row.get("propkey"))
        row["sale_date"] = parse_date(row.get("sale_date"))
        row["sale_price"] = parse_int(row.get("sale_price"))

    # Enrich properties with real geocoded lat/lng and neighborhood from OSM.
    # Reads from cache instantly; new addresses are geocoded in a background thread.
    try:
        from geocoder import enrich_with_geocoding
        enrich_with_geocoding(properties)
    except Exception:
        pass  # geocoder is optional — app works without it

    properties_by_propkey = {row["propkey"]: row for row in properties}
    ownership_by_propkey = {row["propkey"]: row for row in ownership}
    transactions_by_propkey: dict[int, list[dict[str, Any]]] = {}
    for row in transactions:
        transactions_by_propkey.setdefault(row["propkey"], []).append(row)

    property_ownership: list[dict[str, Any]] = []
    for prop in properties:
        owner = ownership_by_propkey.get(prop["propkey"], {})
        property_ownership.append({**prop, **owner})

    return PropertyDataStore(
        properties=properties,
        ownership=ownership,
        transactions=transactions,
        properties_by_propkey=properties_by_propkey,
        ownership_by_propkey=ownership_by_propkey,
        transactions_by_propkey=transactions_by_propkey,
        property_ownership=property_ownership,
    )
