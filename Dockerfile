FROM python:3.11-slim

WORKDIR /app

# System deps for faiss-cpu + sentence-transformers wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        unzip \
        git \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# Copy the rest of the project.
COPY data ./data
COPY scripts ./scripts
COPY Makefile README.md LICENSING.md ./

# Pre-build the indexes inside the image so cold-start is fast.
# (Comment this out if you'd rather mount data at runtime.)
RUN python -m scripts.build_index || true

ENV MEDCODER_LOG_LEVEL=INFO

ENTRYPOINT ["medcoder"]
CMD ["--help"]
