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

# The source tree is importable as-is; no build step means no unhashed build-time downloads.
ENV PYTHONPATH=/app

EXPOSE 8000
CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
