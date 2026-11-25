import os
from pathlib import Path

os.environ["FACTCHECK_AUTO_RUN"] = "false"

TEST_DB = Path(__file__).parent / "test_suite_epic.db"
if os.environ.get("EPIC_PYTEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["EPIC_PYTEST_DATABASE_URL"]
else:
    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

import pytest

from app.core.database import Base, engine


@pytest.fixture(scope="session", autouse=True)
def database_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if not os.environ.get("EPIC_PYTEST_DATABASE_URL") and TEST_DB.exists():
        TEST_DB.unlink()
