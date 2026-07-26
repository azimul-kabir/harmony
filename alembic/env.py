from logging.config import fileConfig

from alembic import context

from app.database.base import Base
from app.database.session import engine
from app.database import models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    # Alembic runs inside Uvicorn during Harmony's FastAPI lifespan.  The
    # default ``fileConfig`` behavior disables every logger not declared in
    # alembic.ini, including ``uvicorn.error``.  That suppresses Uvicorn's
    # "Application startup complete" message and makes a healthy container
    # look permanently stuck at migration startup.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(connection=supplied_connection, target_metadata=target_metadata)
        context.run_migrations()
        return

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
