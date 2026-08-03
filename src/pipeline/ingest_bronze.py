"""Bronze ingest — load CSV into bronze.raw_tickets with lineage + row_hash."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

from src.shared.db import SOURCE_COLUMNS, connect, log_pipeline_run, new_run_id, row_hash

logger = logging.getLogger(__name__)

DEFAULT_CSV = Path(__file__).resolve().parents[2] / "data" / "raw_tickets.csv"


def ingest_bronze(
    csv_path: Optional[Path] = None,
    run_id: Optional[UUID] = None,
    source_file: str = "data/raw_tickets.csv",
) -> dict:
    path = Path(csv_path or DEFAULT_CSV)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    run_id = run_id or new_run_id()
    inserted = 0
    skipped = 0

    with connect() as conn:
        log_pipeline_run(
            conn,
            run_id,
            "bronze",
            "started",
            message=f"Ingesting {path}",
            details={"source_file": source_file},
        )
        try:
            with path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                batch = []
                for row in reader:
                    values = [row.get(c, "") for c in SOURCE_COLUMNS]
                    rh = row_hash(values)
                    batch.append(
                        (
                            *[v if v != "" else None for v in values],
                            source_file,
                            rh,
                            str(run_id),
                        )
                    )
                    if len(batch) >= 500:
                        i, s = _flush(conn, batch)
                        inserted += i
                        skipped += s
                        batch = []
                if batch:
                    i, s = _flush(conn, batch)
                    inserted += i
                    skipped += s

            log_pipeline_run(
                conn,
                run_id,
                "bronze",
                "succeeded",
                row_count=inserted,
                message=f"inserted={inserted} skipped_dupes={skipped}",
                details={"inserted": inserted, "skipped": skipped, "source_file": source_file},
            )
        except Exception as exc:
            log_pipeline_run(
                conn,
                run_id,
                "bronze",
                "failed",
                message=str(exc),
            )
            raise

    logger.info("bronze ingest run_id=%s inserted=%s skipped=%s", run_id, inserted, skipped)
    return {
        "run_id": str(run_id),
        "inserted": inserted,
        "skipped": skipped,
        "source_file": source_file,
    }


def _flush(conn, batch: list[tuple]) -> tuple[int, int]:
    sql = """
        INSERT INTO bronze.raw_tickets (
            ticket_id, created_at, resolved_at, category, priority, status,
            building, description, submitted_by, assigned_to, resolution_notes,
            cost, sla_hours, source_file, row_hash, ingest_run_id
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (row_hash) DO NOTHING
    """
    before = conn.execute("SELECT COUNT(*) AS c FROM bronze.raw_tickets").fetchone()["c"]
    with conn.cursor() as cur:
        cur.executemany(sql, batch)
    after = conn.execute("SELECT COUNT(*) AS c FROM bronze.raw_tickets").fetchone()["c"]
    inserted = after - before
    skipped = len(batch) - inserted
    return inserted, skipped


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(ingest_bronze())
