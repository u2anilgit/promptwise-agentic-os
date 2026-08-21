FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY core ./core
COPY gateway ./gateway
COPY scripts ./scripts
COPY catalog ./catalog
COPY packs/installed ./packs/installed

RUN pip install --no-cache-dir -e .

EXPOSE 8000
CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
