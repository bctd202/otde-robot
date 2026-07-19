#!/bin/sh
set -eu
if [ -n "${FRONTEND_DIST_DIR:-}" ]; then
  echo "Frontend build path: ${FRONTEND_DIST_DIR}"
  test -f "${FRONTEND_DIST_DIR}/index.html"
  test -f "${FRONTEND_DIST_DIR}/favicon.svg"
  test -d "${FRONTEND_DIST_DIR}/assets"
fi
alembic upgrade head
python -c 'from app.db.models import Signal; from app.db.session import SessionLocal; from app.db.seed import seed; db=SessionLocal(); count=db.query(Signal).count(); db.close(); seed() if count == 0 else None'
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
