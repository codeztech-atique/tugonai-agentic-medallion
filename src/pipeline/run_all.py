"""Run bronze → silver → gold end-to-end."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow `python -m src.pipeline.run_all` from repo root
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.build_gold import build_gold
from src.pipeline.ingest_bronze import ingest_bronze
from src.pipeline.transform_silver import transform_silver
from src.shared.db import bootstrap_schema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("pipeline")


def run_all(bootstrap: bool = True) -> dict:
    if bootstrap:
        logger.info("Applying SQL bootstrap…")
        bootstrap_schema()
    bronze = ingest_bronze()
    silver = transform_silver()
    gold = build_gold()
    result = {"bronze": bronze, "silver": silver, "gold": gold}
    logger.info("Pipeline complete: %s", result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Run medallion pipeline")
    parser.add_argument("--no-bootstrap", action="store_true", help="Skip SQL bootstrap")
    args = parser.parse_args()
    run_all(bootstrap=not args.no_bootstrap)


if __name__ == "__main__":
    main()
