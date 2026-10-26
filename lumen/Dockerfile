# syntax=docker/dockerfile:1
# ---------- stage 1: build the React UI --------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: Python dependencies (wheels built once, no compilers in the final image) ----
FROM python:3.12-slim AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r /tmp/requirements.txt

# ---------- stage 3: runtime ----------------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    UPLOAD_DIR=/data/uploads
RUN groupadd --system lumen && useradd --system --gid lumen --home-dir /app --shell /usr/sbin/nologin lumen
COPY --from=deps /opt/venv /opt/venv
WORKDIR /app
COPY --chown=root:root backend/app backend/app
COPY --chown=root:root backend/alembic backend/alembic
COPY --chown=root:root backend/alembic.ini backend/requirements.txt backend/
COPY --chown=root:root sample_data/generate.py sample_data/generate.py
COPY --from=web --chown=root:root /web/dist frontend/dist
# Pre-generate the demo dataset at build time (deterministic) so "Load demo" works offline.
RUN cd sample_data && python generate.py > /dev/null \
 && mkdir -p /data/uploads && chown -R lumen:lumen /data
USER lumen
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
