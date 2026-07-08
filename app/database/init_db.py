from app.database.base import Base
from app.database.database import engine

# Import models so SQLAlchemy knows about them
from app.database import models  # noqa: F401


def init_db() -> None:
    Base.metadata.create_all(bind=engine)