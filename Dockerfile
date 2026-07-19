FROM node:22-alpine AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONPATH=/app \
    DATABASE_URL=sqlite:////data/liquidity_hunter.db \
    FRONTEND_DIST_DIR=/app/frontend/dist \
    MARKET_DATA_PROVIDER=mock \
    PAPER_ONLY=true \
    PORT=8000
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY backend/docker-entrypoint.sh ./docker-entrypoint.sh
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist
RUN test -f /app/frontend/dist/index.html \
    && test -d /app/frontend/dist/assets \
    && chmod +x docker-entrypoint.sh \
    && mkdir -p /data
EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
