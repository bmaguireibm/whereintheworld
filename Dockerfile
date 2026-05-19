# ── Builder Stage: Generate the optimized GeoParquet ─────────
FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir duckdb>=1.1.0 pyarrow pandas numpy

WORKDIR /build
COPY scripts/02_build_parquet.py ./build_parquet.py

ENV OUTPUT_PATH=/build/data/geolocator_v2.parquet

# Generate geoparquet from Overture Maps S3
# (public bucket, no credentials needed)
RUN python build_parquet.py

# ── Server Stage: Minimal runtime ─────────────────────────────
FROM python:3.12-slim AS server

RUN pip install --no-cache-dir \
    duckdb>=1.1.0 \
    fastapi>=0.115.0 \
    uvicorn>=0.30.0

WORKDIR /app

COPY server.py .
COPY --from=builder /build/data/geolocator_v2.parquet ./data/geolocator_v2.parquet

ENV PARQUET_PATH=/app/data/geolocator_v2.parquet
ENV PORT=8080
ENV HOST=0.0.0.0

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python", "server.py"]
