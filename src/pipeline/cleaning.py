"""Silver cleaning helpers — normalize messy ticket fields."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from dateutil import parser as date_parser

PRIORITY_MAP = {
    "critical": "critical",
    "crit": "critical",
    "urgent!!!": "critical",
    "asap": "critical",
    "high": "high",
    "hi": "high",
    "medium": "medium",
    "med": "medium",
    "normal": "medium",
    "low": "low",
    "lo": "low",
}

STATUS_MAP = {
    "open": "open",
    "in progress": "in_progress",
    "pending vendor": "pending_vendor",
    "escalated": "escalated",
    "resolved": "resolved",
    "closed": "closed",
}

CATEGORY_MAP = {
    "power issue": "electrical",
    "electrical": "electrical",
    "fire safety": "fire_safety",
    "fire/safety": "fire_safety",
    "a/c": "hvac",
    "hvac": "hvac",
    "pest control": "pest_control",
    "pest": "pest_control",
    "exterminator": "pest_control",
    "plumbing issue": "plumbing",
    "plumbing": "plumbing",
    "janitorial": "cleaning",
    "cleaning": "cleaning",
    "general maintenance": "general_maintenance",
    "security": "security",
    "elevator": "elevator",
    "network": "network",
    "sprinkler": "fire_safety",
}


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"null", "none", "n/a", "na", "???"}:
        return None
    return text


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    text = _blank_to_none(value)
    if text is None:
        return None
    try:
        return date_parser.parse(text, fuzzy=True, dayfirst=False)
    except (ValueError, OverflowError, TypeError):
        try:
            return date_parser.parse(text, fuzzy=True, dayfirst=True)
        except (ValueError, OverflowError, TypeError):
            return None


def normalize_priority(raw: Optional[str]) -> tuple[Optional[str], Optional[str], list[str]]:
    flags: list[str] = []
    original = _blank_to_none(raw)
    if original is None:
        return "unknown", None, ["priority_missing"]
    key = original.lower()
    mapped = PRIORITY_MAP.get(key)
    if mapped is None:
        flags.append("priority_unmapped")
        return "unknown", original, flags
    if mapped != key:
        flags.append("priority_normalized")
    return mapped, original, flags


def normalize_status(raw: Optional[str]) -> tuple[Optional[str], Optional[str], list[str]]:
    flags: list[str] = []
    original = _blank_to_none(raw)
    if original is None:
        return "unknown", None, ["status_missing"]
    key = original.lower()
    mapped = STATUS_MAP.get(key)
    if mapped is None:
        flags.append("status_unmapped")
        return "unknown", original, flags
    return mapped, original, flags


def normalize_category(raw: Optional[str]) -> tuple[Optional[str], Optional[str], list[str]]:
    flags: list[str] = []
    original = _blank_to_none(raw)
    if original is None:
        return "unknown", None, ["category_missing"]
    key = original.lower()
    if key in CATEGORY_MAP:
        mapped = CATEGORY_MAP[key]
        if mapped != key.replace(" ", "_").replace("/", "_"):
            flags.append("category_normalized")
        return mapped, original, flags
    # slugify unknown but keep readable
    slug = re.sub(r"[^a-z0-9]+", "_", key).strip("_") or "unknown"
    flags.append("category_unmapped")
    return slug, original, flags


def parse_numeric(raw: Optional[str]) -> tuple[Optional[float], list[str]]:
    flags: list[str] = []
    text = _blank_to_none(raw)
    if text is None:
        return None, flags
    cleaned = text.replace(",", "").replace("$", "")
    try:
        return float(cleaned), flags
    except ValueError:
        flags.append("numeric_invalid")
        return None, flags


def is_valid_ticket_id(raw: Optional[str]) -> bool:
    text = _blank_to_none(raw)
    if text is None:
        return False
    return bool(re.match(r"^TKT-\d+$", text, re.I)) or len(text) > 0


def clean_bronze_row(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return silver-shaped dict or None if row should be dropped."""
    flags: list[str] = []
    ticket_id = _blank_to_none(row.get("ticket_id"))
    if not is_valid_ticket_id(ticket_id):
        return None

    created_at = parse_datetime(row.get("created_at"))
    resolved_at = parse_datetime(row.get("resolved_at"))
    date_anomaly = False
    if created_at and resolved_at and resolved_at < created_at:
        resolved_at = None
        date_anomaly = True
        flags.append("date_anomaly")

    priority, priority_raw, pflags = normalize_priority(row.get("priority"))
    status, status_raw, sflags = normalize_status(row.get("status"))
    category, category_raw, cflags = normalize_category(row.get("category"))
    flags.extend(pflags + sflags + cflags)

    cost, cost_flags = parse_numeric(row.get("cost"))
    sla_hours, sla_flags = parse_numeric(row.get("sla_hours"))
    flags.extend(cost_flags + sla_flags)

    resolution_hours = None
    sla_breached = None
    if created_at and resolved_at:
        resolution_hours = (resolved_at - created_at).total_seconds() / 3600.0
        if sla_hours is not None:
            sla_breached = resolution_hours > float(sla_hours)

    return {
        "ticket_id": ticket_id,
        "created_at": created_at,
        "resolved_at": resolved_at,
        "category": category,
        "category_raw": category_raw,
        "priority": priority,
        "priority_raw": priority_raw,
        "status": status,
        "status_raw": status_raw,
        "building": _blank_to_none(row.get("building")),
        "description": _blank_to_none(row.get("description")),
        "submitted_by": _blank_to_none(row.get("submitted_by")),
        "assigned_to": _blank_to_none(row.get("assigned_to")),
        "resolution_notes": _blank_to_none(row.get("resolution_notes")),
        "cost": cost,
        "sla_hours": sla_hours,
        "resolution_hours": resolution_hours,
        "sla_breached": sla_breached,
        "date_anomaly": date_anomaly,
        "source_row_hash": row.get("row_hash"),
        "bronze_ingested_at": row.get("ingested_at"),
        "cleaning_flags": flags,
    }
