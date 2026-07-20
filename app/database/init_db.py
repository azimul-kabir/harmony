from pathlib import Path

from alembic import command
from alembic.config import Config

from app.database.base import Base
from app.database.database import engine

# Import models so SQLAlchemy knows about them.
from app.database import models  # noqa: F401


def init_db() -> None:
    # Preserve the existing first-start experience, then let Alembic apply
    # additive upgrades to both new and existing installations.
    Base.metadata.create_all(bind=engine)

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
