"""Apply Alembic migrations at startup.

- Fresh database: create everything via migrations.
- Database created before migrations existed (tables via create_all, no alembic_version):
  stamp it at the baseline revision, then apply newer migrations.
- Already-migrated database: apply any pending migrations.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

logger = logging.getLogger("lostlink.migrate")

BACKEND_DIR = Path(__file__).resolve().parents[2]
BASELINE = "0001"


def _config(connection) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["connection"] = connection
    cfg.attributes["skip_logging"] = True
    return cfg


def run_migrations(engine: Engine, target: str = "head") -> None:
    # Alembic opens its own transaction here. Do not open one first: PostgreSQL migrations use
    # autocommit_block() (ALTER TYPE ... ADD VALUE), which needs Alembic to own the transaction.
    tables = set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        cfg = _config(conn)
        if "alembic_version" not in tables and "item_reports" in tables:
            logger.info("Existing pre-migration database detected; stamping baseline %s", BASELINE)
            command.stamp(cfg, BASELINE)
        command.upgrade(cfg, target)
