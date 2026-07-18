FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY docker-entrypoint.sh .
ENV PYTHONPATH=/app
RUN chmod +x docker-entrypoint.sh
CMD ["./docker-entrypoint.sh"]
