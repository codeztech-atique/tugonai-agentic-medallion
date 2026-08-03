"""
Medallion DB MCP Server — FastMCP (AgentCore Runtime)

Local:  python main.py
Deploy: agentcore deploy --region ap-south-1
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional
from uuid import UUID

from mcp.server.fastmcp import FastMCP

from db import (
    ALLOWED_SCHEMAS,
    assert_sql_allowlisted,
    bootstrap_schema,
    connect,
    is_select_only,
    log_pipeline_run,
    validate_ident,
    validate_schema,
)
from ingest import ingest_bronze

mcp = FastMCP("medallion-db", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


def _json(data) -> str:
    return json.dumps(data, default=str)


def _csv_path() -> Path:
    if os.environ.get("CSV_PATH"):
        return Path(os.environ["CSV_PATH"])
    here = Path(__file__).parent / "data" / "raw_tickets.csv"
    if here.exists():
        return here
    return Path(__file__).resolve().parents[3] / "data" / "raw_tickets.csv"


@mcp.tool()
def list_schemas_tables() -> str:
    """List tables in bronze, silver, gold, and meta schemas."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = ANY(%s)
              AND table_type = 'BASE TABLE'
            ORDER BY 1, 2
            """,
            (list(ALLOWED_SCHEMAS),),
        ).fetchall()
    return _json(rows)


@mcp.tool()
def describe_table(schema: str, table: str) -> str:
    """Describe columns for a table in an allowlisted medallion schema."""
    schema = validate_schema(schema)
    table = validate_ident(table, "table")
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        ).fetchall()
    if not rows:
        return _json({"error": f"Table {schema}.{table} not found"})
    return _json({"schema": schema, "table": table, "columns": rows})


@mcp.tool()
def sample_rows(schema: str, table: str, limit: int = 20) -> str:
    """Sample rows from an allowlisted table (max 100)."""
    schema = validate_schema(schema)
    table = validate_ident(table, "table")
    limit = max(1, min(int(limit), 100))
    sql = f'SELECT * FROM "{schema}"."{table}" LIMIT %s'
    with connect() as conn:
        rows = conn.execute(sql, (limit,)).fetchall()
    return _json({"schema": schema, "table": table, "rows": rows})


@mcp.tool()
def profile_table(schema: str, table: str, columns: Optional[str] = None) -> str:
    """Profile null rates and cardinality. Optional columns: comma-separated names."""
    schema = validate_schema(schema)
    table = validate_ident(table, "table")
    with connect() as conn:
        col_rows = conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        ).fetchall()
        if not col_rows:
            return _json({"error": f"Table {schema}.{table} not found"})

        wanted = {c.strip() for c in columns.split(",") if c.strip()} if columns else None
        total = conn.execute(f'SELECT COUNT(*) AS c FROM "{schema}"."{table}"').fetchone()["c"]
        profiles = []
        for col in col_rows:
            name = col["column_name"]
            if wanted and name not in wanted:
                continue
            validate_ident(name, "column")
            try:
                stats = conn.execute(
                    f'''
                    SELECT
                        COUNT(*) FILTER (WHERE "{name}" IS NULL) AS nullish,
                        COUNT(DISTINCT "{name}") AS approx_distinct
                    FROM "{schema}"."{table}"
                    '''
                ).fetchone()
            except Exception as exc:
                profiles.append({"column": name, "error": str(exc)})
                continue
            nullish = stats["nullish"] or 0
            profiles.append(
                {
                    "column": name,
                    "data_type": col["data_type"],
                    "nullish_count": nullish,
                    "nullish_rate": round(nullish / total, 4) if total else None,
                    "approx_distinct": stats["approx_distinct"],
                }
            )
    return _json({"schema": schema, "table": table, "row_count": total, "columns": profiles})


@mcp.tool()
def run_sql_readonly(sql: str) -> str:
    """Run a single SELECT/WITH query against medallion schemas (max 500 rows)."""
    if not is_select_only(sql):
        return _json({"error": "Only a single SELECT/WITH statement is allowed"})
    assert_sql_allowlisted(sql)
    with connect() as conn:
        rows = conn.execute(sql).fetchmany(500)
    return _json({"row_count": len(rows), "rows": rows})


@mcp.tool()
def execute_sql(sql: str) -> str:
    """Execute DDL/DML against bronze/silver/gold/meta only."""
    assert_sql_allowlisted(sql)
    if is_select_only(sql):
        return _json({"error": "Use run_sql_readonly for SELECT"})
    with connect() as conn:
        cur = conn.execute(sql)
        return _json({"ok": True, "rowcount": cur.rowcount, "message": "executed"})


@mcp.tool()
def ingest_bronze_csv(source_file: str = "data/raw_tickets.csv", run_id: Optional[str] = None) -> str:
    """Idempotently ingest support tickets CSV into bronze.raw_tickets with lineage."""
    try:
        bootstrap_schema()
    except Exception:
        pass
    rid = UUID(run_id) if run_id else None
    result = ingest_bronze(csv_path=_csv_path(), run_id=rid, source_file=source_file)
    return _json(result)


@mcp.tool()
def log_pipeline_run_tool(
    run_id: str,
    layer: str,
    status: str,
    row_count: Optional[int] = None,
    message: Optional[str] = None,
    details_json: Optional[str] = None,
) -> str:
    """Write a pipeline run record into meta.pipeline_runs."""
    details = json.loads(details_json) if details_json else {}
    with connect() as conn:
        log_pipeline_run(
            conn,
            UUID(run_id),
            layer,
            status,
            row_count=row_count,
            message=message,
            details=details,
        )
    return _json({"ok": True, "run_id": run_id, "layer": layer, "status": status})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
