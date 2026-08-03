from src.pipeline.cleaning import clean_bronze_row, normalize_category, normalize_priority


def test_priority_aliases():
    assert normalize_priority("HI")[0] == "high"
    assert normalize_priority("crit")[0] == "critical"
    assert normalize_priority("???")[0] == "unknown"


def test_category_synonyms():
    assert normalize_category("power issue")[0] == "electrical"
    assert normalize_category("Fire/Safety")[0] == "fire_safety"


def test_clean_row_and_drop():
    base = {
        "ticket_id": "TKT-9",
        "created_at": "2024-01-01T00:00:00",
        "resolved_at": "2024-01-02T00:00:00",
        "category": "HVAC",
        "priority": "med",
        "status": "Open",
        "building": "A",
        "description": "too cold",
        "submitted_by": "x",
        "assigned_to": "y",
        "resolution_notes": None,
        "cost": "10",
        "sla_hours": "4",
        "row_hash": "h",
        "ingested_at": None,
    }
    out = clean_bronze_row(base)
    assert out["priority"] == "medium"
    assert out["status"] == "open"
    assert clean_bronze_row({**base, "ticket_id": ""}) is None
