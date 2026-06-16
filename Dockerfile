FROM python:3.12-slim

# Instalar deps de sistema como root
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# HuggingFace Spaces requiere UID 1000
RUN useradd -m -u 1000 user

USER user
ENV PATH="/home/user/.local/bin:$PATH" \
    PYTHONUTF8=1 \
    EVENTSCOPE_DATABASE_URL="sqlite:////home/user/data/eventscope.db"

WORKDIR /home/user/app

COPY --chown=user pyproject.toml README.md ./
COPY --chown=user src/ src/

RUN pip install --no-cache-dir -e . && mkdir -p /home/user/data

EXPOSE 7860

CMD ["sh", "-c", "eventscope init-db && eventscope serve --host 0.0.0.0 --port ${PORT:-7860}"]
