import os
from pathlib import Path


os.environ.setdefault(
    "FRONTEND_DIST_DIR",
    str(Path(__file__).parent / "static_site"),
)
os.environ.setdefault("ENABLE_DEMO_OPTION_CONTRACTS", "true")


def pytest_sessionstart(session):
    """Route tests use the configured app database, so create its complete test schema."""
    from app.db import models  # noqa: F401
    from app.db.session import Base, engine
    Base.metadata.create_all(engine)
