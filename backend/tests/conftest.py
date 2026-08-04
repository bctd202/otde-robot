import os
from pathlib import Path


os.environ.setdefault(
    "FRONTEND_DIST_DIR",
    str(Path(__file__).parent / "static_site"),
)
os.environ.setdefault("MARKET_DATA_PROVIDER", "mock")
