#!/bin/sh
set -eu
alembic upgrade head
python -c 'from app.db.models import Signal; from app.db.session import SessionLocal; from app.db.seed import seed; db=SessionLocal(); count=db.query(Signal).count(); db.close(); seed() if count == 0 else None'
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
