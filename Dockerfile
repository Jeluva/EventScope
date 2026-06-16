FROM python:3.12-slim

# HuggingFace Spaces requiere usuario no-root con UID 1000
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH" \
    PYTHONUTF8=1

WORKDIR /app

# Install system deps (como root antes de cambiar de usuario — psycopg necesita libpq)
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*
USER user

COPY --chown=user pyproject.toml README.md ./
COPY --chown=user src/ src/

RUN pip install --no-cache-dir -e .

RUN mkdir -p /home/user/data

# HuggingFace Spaces usa 7860; PORT env lo overridea en otros hosts
EXPOSE 7860

ENV EVENTSCOPE_DATABASE_URL="sqlite:////home/user/data/eventscope.db"

CMD ["sh", "-c", "eventscope init-db && eventscope serve --host 0.0.0.0 --port ${PORT:-7860}"]
