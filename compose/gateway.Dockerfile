# Dashboard bundle: built from the committed package-lock (npm ci verifies integrity hashes,
# lifecycle scripts disabled). Only the static output is copied into the runtime image.
FROM node:22-slim AS dashboard
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --ignore-scripts
COPY dashboard ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

# Dependencies come only from the hash-pinned lock (pip verifies every wheel's
# sha256). Regenerate with the commands in docs/MAINTENANCE.md section 6.
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY pyproject.toml ./
COPY core ./core
COPY gateway ./gateway
COPY scripts ./scripts
COPY catalog ./catalog
COPY policies ./policies
COPY security ./security
COPY tool_registry.yaml ./
COPY packs/installed ./packs/installed
COPY --from=dashboard /dashboard/dist ./dashboard/dist

# The source tree is importable as-is; no build step means no unhashed build-time downloads.
ENV PYTHONPATH=/app

EXPOSE 8000
CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
