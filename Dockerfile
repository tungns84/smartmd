FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY models.toml ./models.toml

RUN pip install --no-cache-dir uv && uv pip install --system -e ".[web]"

ENV WEB_DATA_DIR=/data/web
ENV PDF2MD_CACHE_DIR=/data/cache
EXPOSE 8000
CMD ["pdf2md-web"]
