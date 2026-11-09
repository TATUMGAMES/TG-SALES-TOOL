# TG Sales CRM application image: FastAPI server plus the built web app.
# Build from the repository root:  docker build -f deploy/Dockerfile -t tg-sales .

# ---- web app ---------------------------------------------------------------
FROM node:22.20-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY web/ ./
RUN npm run build

# ---- server ----------------------------------------------------------------
FROM python:3.13.7-slim-trixie AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# PostgreSQL 18 client tools (pg_dump/pg_restore for backups) from the official
# PostgreSQL apt repository, and DejaVu fonts for PDF reports.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg fonts-dejavu-core \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
 && apt-get purge -y curl gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 tgsales
WORKDIR /app
COPY requirements.lock pyproject.toml README.md LICENSE NOTICE TRADEMARKS.md ./
RUN pip install --require-hashes -r requirements.lock
COPY src/ src/
RUN pip install --no-deps .
COPY --from=web /web/dist /app/web
RUN mkdir -p /data && chown tgsales /data
USER tgsales
ENV TG_SALES_HOST=0.0.0.0 \
    TG_SALES_CONTAINER_LOCAL_ONLY=true \
    TG_SALES_PORT=8765 \
    TG_SALES_DATA_DIR=/data \
    TG_SALES_STATIC_DIR=/app/web \
    TG_SALES_PG_BIN=/usr/lib/postgresql/18/bin
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "tg_sales.api"]
