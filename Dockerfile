FROM python:3.12-slim

WORKDIR /app

# Install system deps for psycopg (optional postgres support)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir -e .

# Create data dir for SQLite (overridden by DATABASE_URL env in prod)
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["eventscope", "serve", "--host", "0.0.0.0", "--port", "8000"]
