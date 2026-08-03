"""Silver transform — clean, type, dedupe bronze → silver.tickets."""

from __future__ import annotations

import json
import logging
from typing import Optional
from uuid import UUID

from src.pipeline.cleaning import clean_bronze_row
from src.shared.db import connect, log_pipeline_run, new_run_id

logger = logging.getLogger(__name__)


def transform_silver(run_id: Optional[UUID] = None) -> dict:
    run_id = run_id or new_run_id()
    kept = 0
    dropped = 0

    with connect() as conn:
        log_pipeline_run(conn, run_id, "silver", "started", message="Transforming bronze → silver")
        try:
            rows = conn.execute("SELECT * FROM bronze.raw_tickets").fetchall()
            cleaned_by_id: dict[str, dict] = {}
            for row in rows:
                cleaned = clean_bronze_row(row)
                if cleaned is None:
                    dropped += 1
                    continue
                tid = cleaned["ticket_id"]
                existing = cleaned_by_id.get(tid)
                if existing is None:
                    cleaned_by_id[tid] = cleaned
                    continue
                # Keep latest created_at, then higher source_row_hash
                prev_created = existing.get("created_at")
                new_created = cleaned.get("created_at")
                replace = False
                if new_created and (prev_created is None or new_created > prev_created):
                    replace = True
                elif new_created == prev_created and (cleaned.get("source_row_hash") or "") > (
                    existing.get("source_row_hash") or ""
                ):
                    replace = True
                if replace:
                    cleaned_by_id[tid] = cleaned
                dropped += 1  # duplicate discarded

            conn.execute("TRUNCATE silver.tickets")
            insert_sql = """
                INSERT INTO silver.tickets (
                    ticket_id, created_at, resolved_at, category, category_raw,
                    priority, priority_raw, status, status_raw, building, description,
                    submitted_by, assigned_to, resolution_notes, cost, sla_hours,
                    resolution_hours, sla_breached, date_anomaly, source_row_hash,
                    bronze_ingested_at, silver_run_id, cleaning_flags
                ) VALUES (
                    %(ticket_id)s, %(created_at)s, %(resolved_at)s, %(category)s, %(category_raw)s,
                    %(priority)s, %(priority_raw)s, %(status)s, %(status_raw)s, %(building)s, %(description)s,
                    %(submitted_by)s, %(assigned_to)s, %(resolution_notes)s, %(cost)s, %(sla_hours)s,
                    %(resolution_hours)s, %(sla_breached)s, %(date_anomaly)s, %(source_row_hash)s,
                    %(bronze_ingested_at)s, %(silver_run_id)s, %(cleaning_flags)s::jsonb
                )
            """
            payload = []
            for item in cleaned_by_id.values():
                item = dict(item)
                item["silver_run_id"] = str(run_id)
                item["cleaning_flags"] = json.dumps(item.get("cleaning_flags") or [])
                payload.append(item)
            with conn.cursor() as cur:
                cur.executemany(insert_sql, payload)
            kept = len(payload)

            log_pipeline_run(
                conn,
                run_id,
                "silver",
                "succeeded",
                row_count=kept,
                message=f"kept={kept} dropped_or_duped={dropped}",
                details={"kept": kept, "dropped_or_duped": dropped, "bronze_rows": len(rows)},
            )
        except Exception as exc:
            log_pipeline_run(conn, run_id, "silver", "failed", message=str(exc))
            raise

    logger.info("silver transform run_id=%s kept=%s dropped=%s", run_id, kept, dropped)
    return {"run_id": str(run_id), "kept": kept, "dropped_or_duped": dropped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(transform_silver())
