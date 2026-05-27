import logging
import os
from pathlib import Path

import asyncpg

from app.core.config import settings

logger = logging.getLogger("grain.db.migrate")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
TRACKING_TABLE = "_migrations"
EXPECTED_DIM = 3072


async def _ensure_dimension(conn) -> None:
    """Ensure all embedding columns and match_notes use the correct dimension."""
    logger.info(f"Enforcing vector dimension = {EXPECTED_DIM}")

    # Drop match_notes first — it depends on the column types
    await conn.execute("DROP FUNCTION IF EXISTS match_notes CASCADE")

    for table in ("topics", "notes", "entities"):
        await conn.execute(
            f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({EXPECTED_DIM})"
        )
        logger.info(f"  Altered {table}.embedding → vector({EXPECTED_DIM})")

    # Recreate match_notes with correct dimension
    await conn.execute(
        f"""
        CREATE OR REPLACE FUNCTION match_notes (
          query_embedding vector({EXPECTED_DIM}),
          match_threshold float,
          match_count int
        )
        RETURNS TABLE (
          id UUID,
          raw_text TEXT,
          summary TEXT,
          source_url TEXT,
          source_type TEXT,
          personal_insight TEXT,
          topic_id UUID,
          topic_name TEXT,
          similarity float
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
          RETURN QUERY
          SELECT
            notes.id,
            notes.raw_text,
            notes.summary,
            notes.source_url,
            notes.source_type,
            notes.personal_insight,
            notes.topic_id,
            topics.name AS topic_name,
            (1 - (notes.embedding <=> query_embedding))::float AS similarity
          FROM notes
          LEFT JOIN topics ON notes.topic_id = topics.id
          WHERE notes.embedding IS NOT NULL AND 1 - (notes.embedding <=> query_embedding) > match_threshold
          ORDER BY notes.embedding <=> query_embedding
          LIMIT match_count;
        END;
        $$;
        """
    )
    await conn.execute("NOTIFY pgrst, 'reload schema'")
    logger.info("Vector dimension enforcement complete")


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
        try:
            await _ensure_dimension(conn)
        except Exception:
            logger.exception("Dimension enforcement failed — app will still start")
    except Exception:
        logger.exception("Migration failed")
    finally:
        await conn.close()
