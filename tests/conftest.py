import os
from pathlib import Path


TEST_DATABASE = Path("/private/tmp/harmony-pytest.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE}"


def pytest_sessionstart(session):
    from app.database.base import Base
    from app.database.database import engine
    from app.database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def pytest_sessionfinish(session, exitstatus):
    from app.database.database import engine

    engine.dispose()
    TEST_DATABASE.unlink(missing_ok=True)
