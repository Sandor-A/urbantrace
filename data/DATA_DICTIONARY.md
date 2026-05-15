# Cluj-Napoca Property Sample Data — Field Definitions

This folder contains three files representing a simplified property database for Cluj-Napoca, Romania.

## Files

| File | Rows | Description |
|------|------|-------------|
| properties.csv | ~500 | Core property records across Cluj-Napoca's neighborhoods (cartiere) |
| ownership.csv | ~500 | Current ownership records (one per property) |
| transactions.csv | ~590 | Sales history, 2018–2025 |

## Schema

### properties.csv
| Column | Type | Description |
|--------|------|-------------|
| propkey | int | Unique property identifier |
| address | string | Street address (Romanian street names and numbering) |
| borough | string | Cluj-Napoca neighborhood / cartier (e.g., Mărăști, Gheorgheni, Mănăștur, Zorilor, Bună Ziua) |
| zip | string | Romanian ZIP code (400001–400394) |
| property_class | string | Romanian property classification (e.g., "A - Locuință Unifamilială", "D - Bloc Cu Lift") |
| building_sf | int | Building area in square meters (mp) |
| lot_sf | int | Lot area in square meters (mp) |
| year_built | int | Year the building was constructed |
| units | int | Number of units |
| assessed_value | int | Current assessed property value in RON (Romanian Leu) |

### Property Classes
| Code | Description |
|------|-------------|
| A | Locuință Unifamilială — Single-family home |
| B | Locuință Bifamilială — Two-family home |
| C | Bloc Fără Lift — Walk-up apartment block |
| D | Bloc Cu Lift — Elevator apartment block |
| E | Clădire Comercială — Commercial building |
| F | Spațiu de Birouri — Office space |
| G | Depozit / Industrial — Warehouse / industrial |
| H | Teren Neamenajat — Undeveloped land |

### Neighborhoods (Cartiere)
Mărăști, Gheorgheni, Mănăștur, Florești, Grigorescu, Zorilor, Bună Ziua, Sopor, Europa, Borhanci, Dâmbul Rotund, Între Lacuri, Iris, Someșeni, Baciu

---

### ownership.csv
| Column | Type | Description |
|--------|------|-------------|
| propkey | int | References properties.propkey |
| owner_name | string | Name of the owner (individual or Romanian legal entity) |
| owner_type | string | Individual, Corporation, Trust, Government, or Non-Profit |
| is_srl | boolean | TRUE if owned by an SRL (Societate cu Răspundere Limitată) |
| registration_date | date | Date ownership was registered (YYYY-MM-DD) |

**Owner name patterns:**
- **Individual**: Romanian given name + surname (e.g., "Laura Ionescu", "Bogdan Ardelean")
- **Corporation**: Cluj/Ardeal/Napoca-themed company names ending in SRL or SA (e.g., "Ardeal Group SRL", "Cluj Capital SA")
- **Government**: Primăria Cluj-Napoca, Consiliul Județean Cluj, Guvernul României, Ministerul Educației
- **Non-Profit**: Asociația + descriptive name (e.g., "Asociația Someș Civic")
- **Trust**: Fundația + surname (e.g., "Fundația Blaga")

---

### transactions.csv
| Column | Type | Description |
|--------|------|-------------|
| id | int | Unique transaction identifier |
| propkey | int | References properties.propkey |
| sale_date | date | Date of sale (YYYY-MM-DD) |
| sale_price | int | Sale price in RON (Romanian Leu). 0 may indicate transfers or non-arm's-length deals |
| buyer_name | string | Buyer name (individual or entity) |
| seller_name | string | Seller name (individual or entity) |
| transaction_type | string | Type of transaction: Arm's Length, Multi-Parcel, Related Parties, Partial Interest, Cash Buyer, Flip, Same Party |

---

## Notes

- All data is fictional. Names, addresses, and entities are randomly generated for illustration purposes only.
- Area measurements use **square meters (mp)**, consistent with Romanian real estate practice (not square feet).
- Monetary values are in **RON (Romanian Leu)**. As a rough reference, 1 EUR ≈ 5 RON (rate varies).
- Approximately 80% of properties have at least one transaction record; ~20% have no sales history.
- ~5% of transactions have a sale_price of 0, indicating inheritance transfers, gifts, or other non-arm's-length arrangements.
- The dataset covers Cluj-Napoca city proper and immediate surrounding localities (Florești, Baciu).
- Property data may contain intentional quality issues (missing values, outliers) to reflect real-world messiness.
