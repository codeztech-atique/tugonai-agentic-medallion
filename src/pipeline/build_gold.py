"""Gold aggregations from silver.tickets."""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from src.shared.db import connect, log_pipeline_run, new_run_id

logger = logging.getLogger(__name__)


def build_gold(run_id: Optional[UUID] = None) -> dict:
    run_id = run_id or new_run_id()
    counts: dict[str, int] = {}

    with connect() as conn:
        log_pipeline_run(conn, run_id, "gold", "started", message="Building gold models")
        try:
            rid = str(run_id)

            conn.execute("TRUNCATE gold.ticket_volume_by_building_category")
            conn.execute(
                """
                INSERT INTO gold.ticket_volume_by_building_category
                    (building, category, status, ticket_count, gold_run_id)
                SELECT
                    COALESCE(building, 'unknown'),
                    COALESCE(category, 'unknown'),
                    COALESCE(status, 'unknown'),
                    COUNT(*),
                    %s::uuid
                FROM silver.tickets
                GROUP BY 1, 2, 3
                """,
                (rid,),
            )
            counts["ticket_volume"] = conn.execute(
                "SELECT COUNT(*) AS c FROM gold.ticket_volume_by_building_category"
            ).fetchone()["c"]

            conn.execute("TRUNCATE gold.sla_performance")
            conn.execute(
                """
                INSERT INTO gold.sla_performance (
                    priority, status, ticket_count, avg_resolution_hours,
                    median_resolution_hours, breach_count, breach_rate, gold_run_id
                )
                SELECT
                    COALESCE(priority, 'unknown'),
                    COALESCE(status, 'unknown'),
                    COUNT(*),
                    ROUND(AVG(resolution_hours)::numeric, 2),
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2),
                    COUNT(*) FILTER (WHERE sla_breached IS TRUE),
                    ROUND(
                        (COUNT(*) FILTER (WHERE sla_breached IS TRUE))::numeric
                        / NULLIF(COUNT(*) FILTER (WHERE sla_breached IS NOT NULL), 0),
                        4
                    ),
                    %s::uuid
                FROM silver.tickets
                GROUP BY 1, 2
                """,
                (rid,),
            )
            counts["sla_performance"] = conn.execute(
                "SELECT COUNT(*) AS c FROM gold.sla_performance"
            ).fetchone()["c"]

            conn.execute("TRUNCATE gold.cost_by_assignee")
            conn.execute(
                """
                INSERT INTO gold.cost_by_assignee (
                    assigned_to, ticket_count, tickets_with_cost, total_cost, avg_cost, gold_run_id
                )
                SELECT
                    COALESCE(assigned_to, 'unassigned'),
                    COUNT(*),
                    COUNT(cost),
                    ROUND(COALESCE(SUM(cost), 0)::numeric, 2),
                    ROUND(AVG(cost)::numeric, 2),
                    %s::uuid
                FROM silver.tickets
                GROUP BY 1
                """,
                (rid,),
            )
            counts["cost_by_assignee"] = conn.execute(
                "SELECT COUNT(*) AS c FROM gold.cost_by_assignee"
            ).fetchone()["c"]

            total = sum(counts.values())
            log_pipeline_run(
                conn,
                run_id,
                "gold",
                "succeeded",
                row_count=total,
                message="gold models rebuilt",
                details=counts,
            )
        except Exception as exc:
            log_pipeline_run(conn, run_id, "gold", "failed", message=str(exc))
            raise

    logger.info("gold build run_id=%s counts=%s", run_id, counts)
    return {"run_id": str(run_id), "counts": counts}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(build_gold())
