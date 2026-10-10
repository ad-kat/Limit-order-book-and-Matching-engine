# ── Stage 1: Build C++ executables ────────────────────────────────────────────
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

# Build both binaries in one pass
RUN cmake -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --target lob housing_matcher -j$(nproc)

# ── Stage 2: Python runtime ────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy compiled binaries from Stage 1
COPY --from=cpp-builder /app/build/lob              ./build/lob
COPY --from=cpp-builder /app/build/housing_matcher  ./build/housing_matcher

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY api/ api/
COPY market_feed.py .

# Binary paths
ENV LOB_BINARY=/app/build/lob
ENV HOUSING_MATCHER_BINARY=/app/build/housing_matcher
ENV PYTHONUNBUFFERED=1

# Render provides PORT; default to 10000
EXPOSE 10000

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
