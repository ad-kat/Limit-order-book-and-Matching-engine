# ── Stage 1: Build the C++ engine ─────────────────────────────────────────────
FROM ubuntu:24.04 AS cpp-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake g++ make ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY CMakeLists.txt .
COPY src/ src/
COPY include/ include/
COPY tests/ tests/
COPY data/ data/

RUN cmake -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --target lob -j$(nproc)

# ── Stage 2: Python API ────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy compiled binary from Stage 1
COPY --from=cpp-builder /app/build/lob ./build/lob

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# Copy Python source
COPY api/ api/
# worker script
COPY market_feed.py .
ENV LOB_BINARY=/app/build/lob
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
