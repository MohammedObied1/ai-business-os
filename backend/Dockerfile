FROM python:3.12-slim
WORKDIR /app
# postgresql-client provides pg_dump for the daily backups
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev postgresql-client && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# SEED_DEMO=true adds the demo company on an empty database (off in production)
CMD ["sh", "-c", "alembic upgrade head && if [ \"$SEED_DEMO\" = \"true\" ]; then python -m scripts.seed; fi && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
