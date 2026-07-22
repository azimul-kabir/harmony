from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.database.base import Base
from app.database.database import engine

# Import models so SQLAlchemy knows about them.
from app.database import models  # noqa: F401


def init_db() -> None:
    # A brand-new installation is bootstrapped from the current ORM schema and
    # stamped at head.  The migration chain deliberately starts from Harmony's
    # pre-existing ``songs`` table, so running it against an empty database is
    # neither necessary nor valid.  Existing databases retain the additive
    # upgrade path below.
    is_fresh = "songs" not in inspect(engine).get_table_names()
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if is_fresh:
            # The historical migration chain begins with Harmony's original
            # schema, so a truly new database is created from the current ORM
            # metadata and stamped rather than replaying legacy migrations.
            Base.metadata.create_all(bind=connection)
            command.stamp(config, "head")
        else:
            # Do not call create_all before upgrading an existing database.
            # It would create tables from a later ORM schema (for example,
            # metadata_suggestions) before Alembic reaches the revision that
            # owns them, causing the upgrade to fail with "table already
            # exists" and the container to restart continuously.
            command.upgrade(config, "head")
