"""Local DB helpers for the Medallion MCP container (self-contained)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

ALLOWED_SCHEMAS = frozenset({"bronze", "silver", "gold", "meta"})
SOURCE_COLUMNS = [
    "ticket_id",
    "created_at",
    "resolved_at",
    "category",
    "priority",
    "status",
    "building",
    "description",
    "submitted_by",
    "assigned_to",
    "resolution_notes",
    "cost",
    "sla_hours",
]

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN = re.compile(
    r"\b(drop\s+database|drop\s+schema|pg_sleep|dblink|copy\s+|lo_import|lo_export)\b",
    re.I,
)


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


@contextmanager
def connect(autocommit: bool = False):
    conn = psycopg.connect(get_database_url(), row_factory=dict_row, autocommit=autocommit)
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def validate_ident(name: str, kind: str = "identifier") -> str:
    if not _IDENT.match(name):
        raise ValueError(f"Invalid {kind}: {name!r}")
    return name


def validate_schema(schema: str) -> str:
    schema = validate_ident(schema, "schema")
    if schema not in ALLOWED_SCHEMAS:
        raise ValueError(f"Schema not allowed: {schema}")
    return schema


def row_hash(values: Iterable[Optional[str]]) -> str:
    payload = "||".join("" if v is None else str(v) for v in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def new_run_id() -> UUID:
    return uuid4()


def log_pipeline_run(
    conn,
    run_id: UUID,
    layer: str,
    status: str,
    row_count: Optional[int] = None,
    message: Optional[str] = None,
    details: Optional[dict] = None,
    started_at: Optional[datetime] = None,
) -> None:
    finished = datetime.now(timezone.utc) if status in ("succeeded", "failed") else None
    conn.execute(
        """
        INSERT INTO meta.pipeline_runs
            (run_id, layer, status, row_count, message, started_at, finished_at, details)
        VALUES (%s, %s, %s, %s, %s, COALESCE(%s, NOW()), %s, %s::jsonb)
        """,
        (
            str(run_id),
            layer,
            status,
            row_count,
            message,
            started_at,
            finished,
            json.dumps(details or {}),
        ),
    )


def is_select_only(sql: str) -> bool:
    cleaned = sql.strip().rstrip(";").strip()
    if ";" in cleaned:
        return False
    lowered = cleaned.lower().lstrip("(")
    return lowered.startswith("select") or lowered.startswith("with")


def assert_sql_allowlisted(sql: str) -> None:
    if _FORBIDDEN.search(sql):
        raise ValueError("SQL contains forbidden operations")
    for match in re.finditer(r"\b([a-z_][a-z0-9_]*)\s*\.\s*([a-z_][a-z0-9_]*)\b", sql, re.I):
        schema = match.group(1).lower()
        if schema in ("public", "information_schema", "pg_catalog"):
            continue
        if schema not in ALLOWED_SCHEMAS:
            raise ValueError(f"SQL references non-allowlisted schema: {schema}")


def bootstrap_schema(sql_dir: Optional[Path] = None) -> None:
    root = sql_dir or Path(__file__).parent / "sql"
    with connect() as conn:
        for name in ("001_bootstrap.sql", "002_silver_gold.sql"):
            path = root / name
            if path.exists():
                conn.execute(path.read_text(encoding="utf-8"))
