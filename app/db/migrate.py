import logging
import os
from pathlib import Path

import asyncpg

from app.core.config import settings

logger = logging.getLogger("grain.db.migrate")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
TRACKING_TABLE = "_migrations"


async def run_pending() -> None:
    """Connect to Postgres directly and apply any unapplied migration files."""
    if not settings.DATABASE_URL:
        logger.warning("DATABASE_URL not set — skipping migrations")
        return

    try:
        conn = await asyncpg.connect(settings.DATABASE_URL, ssl="require")
    except Exception:
        logger.exception("Cannot reach database — skipping migrations (app will still start)")
        return
    try:
        # Ensure tracking table exists
        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TRACKING_TABLE} (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now())
            )
            """
        )

        # Gather migration files in order
        sql_files = sorted(
            f for f in os.listdir(MIGRATIONS_DIR)
            if f.endswith(".sql") and f != "000_drop_all.sql"
        )

        for filename in sql_files:
            row = await conn.fetchrow(
                f"SELECT 1 FROM {TRACKING_TABLE} WHERE filename = $1", filename
            )
            if row:
                logger.debug(f"Skipping already-applied migration: {filename}")
                continue

            path = MIGRATIONS_DIR / filename
            sql = path.read_text(encoding="utf-8")
            logger.info(f"Applying migration: {filename}")

            # Execute the full SQL file in a transaction
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    f"INSERT INTO {TRACKING_TABLE} (filename) VALUES ($1)",
                    filename,
                )

        logger.info("All pending migrations applied successfully")
    except Exception:
        logger.exception("Migration failed")
        raise
    finally:
        await conn.close()
