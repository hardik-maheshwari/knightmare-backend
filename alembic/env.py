import asyncio
import os
from sqlalchemy.engine import Connection
from dotenv import load_dotenv
import config as app_config

load_dotenv()

print("--- .env file loaded ---")

import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)
print(f"--- Project root added to sys.path: {project_root} ---")

from app.logger_setup import get_logger

logger = get_logger(__name__)
logger.info("Custom logger initialized successfully for alembic.env.")


from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

logger.info("SQLAlchemy and Alembic components imported.")

try:
    from app.extensions import Base
    from app.auth.models import *
    from app.game.models import *

    logger.info("Application models (User, Game, Move) imported successfully.")
except ImportError as e:
    logger.error(f"!!! FAILED to import application models: {e} !!!")
    # Exit if we can't even find the models
    sys.exit(1)

# --- Standard Alembic Config ---
config = context.config
if config.config_file_name is not None:
    logger.info(f"Alembic config file found: {config.config_file_name}")

target_metadata = Base.metadata
logger.info("target_metadata assigned from Base.metadata.")

# --- Migration Functions ---


def do_run_migrations(connection: Connection):
    logger.info("do_run_migrations: Configuring context with connection.")
    context.configure(connection=connection, target_metadata=target_metadata) 
    logger.info("do_run_migrations: Beginning transaction and running migrations.")
    with context.begin_transaction():
        context.run_migrations()
    logger.info("do_run_migrations: Completed.")


def run_migrations_offline() -> None:
    logger.warning("Running in OFFLINE mode.")
    url = app_config.DATABASE_URL  # Get URL directly for offline mode too
    logger.info(f"Offline mode URL from os.getenv: {url}")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    logger.info("run_async_migrations: Starting.")

    db_url = app_config.DATABASE_URL
    logger.info(f"Step 1: Read DATABASE_URL from environment: '{db_url}'")

    if not db_url:
        logger.error(
            "!!! FATAL: DATABASE_URL environment variable is not set or is empty. !!!"
        )
        raise ValueError("DATABASE_URL environment variable is not set or is empty.")

    config_options = {"url": db_url}
    logger.info(f"Step 2: Created config dictionary for engine: {config_options}")

    try:
        logger.info("Step 3: Calling async_engine_from_config...")
        connectable = async_engine_from_config(
            config_options,
            prefix="",  # We are not using a prefix like 'sqlalchemy.'
            poolclass=pool.NullPool,
        )
        logger.info("Step 3: async_engine_from_config call SUCCEEDED.")
    except Exception as e:
        logger.error(
            f"!!! FATAL: Error during async_engine_from_config: {e} !!!", exc_info=True
        )
        raise

    logger.info("Step 4: Connecting to the database...")
    async with connectable.connect() as connection:
        logger.info("Step 4: Connection SUCCEEDED.")
        await connection.run_sync(do_run_migrations)  # type: ignore

    logger.info("Step 5: Disposing of the engine.")
    await connectable.dispose()
    logger.info("run_async_migrations: Completed successfully.")


def run_migrations_online():
    logger.info("Running in ONLINE mode.")
    try:
        asyncio.run(run_async_migrations())
    except Exception as e:
        logger.error(
            f"!!! An error occurred during run_migrations_online: {e} !!!",
            exc_info=True,
        )


# --- Main Entry Point ---
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
