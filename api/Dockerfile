FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gosu libgomp1 libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY api/pyproject.toml ./
COPY api/app ./app
RUN pip install ".[tessera,dev]"

COPY api/tests ./tests
COPY sample-data ./sample-data

COPY db ./db
COPY api/entrypoint.sh /usr/local/bin/nasmap-entrypoint
RUN chmod +x /usr/local/bin/nasmap-entrypoint \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home --shell /bin/bash app \
    && mkdir -p /data/uploads /data/tessera /data/tiles \
    && chown -R app:app /app /data

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/nasmap-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
