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
    Base.metadata.create_all(bind=engine)

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if is_fresh:
            command.stamp(config, "head")
        else:
            command.upgrade(config, "head")
