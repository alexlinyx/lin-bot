FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so Docker layer caching skips reinstalls when only
# source changes.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations

# Migrations run before the server starts so the schema always matches the code.
CMD ["sh", "-c", "alembic upgrade head && uvicorn linbot.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
