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

# Install Python deps first for layer caching. README.md is copied before the
# editable install because pyproject.toml (`readme = "README.md"`) is read by
# setuptools during metadata generation.
COPY pyproject.toml README.md ./
COPY src ./src
# Install CPU-only torch BEFORE the editable install so pip does NOT pull the
# CUDA build (this image has no GPU): torch's default linux wheel drags in
# ~3 GB of nvidia-cu* libraries. Pinning the CPU wheel index keeps the image
# lean — build-verified 2026-06-26 at ~2.75 GB (torch 2.12.1+cpu), with
# `medcoder --help` and the no-LLM `retrieve` smoke both passing in-container.
# Source: https://pytorch.org/get-started/locally/ (CPU wheel index)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -e .

# Copy the rest of the project.
COPY data ./data
COPY scripts ./scripts
COPY Makefile LICENSING.md ./

# Pre-build the indexes inside the image so cold-start is fast.
# (Comment this out if you'd rather mount data at runtime.)
RUN python -m scripts.build_index || true

ENV MEDCODER_LOG_LEVEL=INFO

ENTRYPOINT ["medcoder"]
CMD ["--help"]
